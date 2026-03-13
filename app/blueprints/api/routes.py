from flask import jsonify, request, session
from . import api_bp
from app.extensions import db
from app.models import (
    User,
    Team,
    TeamMember,
    Hackathon,
    HackathonStatus,
    UserRole,
    TeamQR,
    TeamMealUsage,
    TeamJoinRequest,
    TeamVisibility,
    QRLog,
    Evaluation,
    ScanLog,
)
from sqlalchemy import and_, text, func
from datetime import datetime, timedelta


def _admin_only():
    return session.get('role') == 'admin'


def _date_key(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d')

@api_bp.route('/status')
def status():
    return jsonify({'status': 'ok'})

@api_bp.route('/hackathon/<int:hackathon_id>/solo_participants', methods=['GET'])
def get_solo_participants(hackathon_id):
    """
    Get solo participants (team_id = NULL) for a hackathon
    Filter by skills if provided
    """
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
    if hackathon.status != HackathonStatus.REGISTRATION_OPEN:
        return jsonify({'error': 'Registration not open'}), 400
    
    skills_filter = request.args.get('skills', '').strip()
    
    # Get users who are participants AND not in any team
    # AND have active visibility for this hackathon.
    solo_query = (
        db.session.query(User)
        .join(TeamVisibility, TeamVisibility.user_id == User.id)
        .filter(
            User.role == UserRole.PARTICIPANT,
            User.is_public == True,
            TeamVisibility.hackathon_id == hackathon_id,
            TeamVisibility.is_active == True,
            ~User.id.in_(
                db.session.query(TeamMember.user_id)
            )
        )
    )
    
    if skills_filter:
        requested_skills = [s.strip().lower() for s in skills_filter.split(',')]
        for skill in requested_skills:
            solo_query = solo_query.filter(User.skills.ilike(f'%{skill}%'))
    
    solo_participants = solo_query.all()
    
    result = []
    for user in solo_participants:
        result.append({
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'skills': user.skills,
            'experience_level': user.experience_level,
            'college': user.college
        })
    
    return jsonify({'participants': result}), 200

@api_bp.route('/hackathon/<int:hackathon_id>/team/<int:team_id>/add_member', methods=['POST'])
def add_member_to_team(hackathon_id, team_id):
    """
    Team leader sends a join request to a solo participant
    """
    if session.get('role') != 'participant':
        return jsonify({'error': 'Unauthorized'}), 403
    
    user_id = session.get('user_id')
    data = request.get_json()
    participant_id = data.get('participant_id')
    
    if not participant_id:
        return jsonify({'error': 'participant_id required'}), 400
    
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    team = Team.query.get_or_404(team_id)
    participant = User.query.get_or_404(participant_id)
    
    # Validation 1: Must be team leader
    if team.leader_id != user_id:
        return jsonify({'error': 'Only team leader can add members'}), 403
    
    # Validation 2: Team belongs to hackathon
    if team.hackathon_id != hackathon_id:
        return jsonify({'error': 'Team does not belong to this hackathon'}), 400
    
    # Validation 3: Hackathon must be in REGISTRATION_OPEN
    if hackathon.status != HackathonStatus.REGISTRATION_OPEN:
        return jsonify({'error': 'Registration not open'}), 400
    
    # Validation 4: Registration must not be locked
    if team.is_closed:
        return jsonify({'error': 'Team registration is closed'}), 400
    
    # Validation 5: Team must not be full
    current_members = TeamMember.query.filter_by(team_id=team_id).count()
    if current_members >= hackathon.max_team_size:
        return jsonify({'error': 'Team is full'}), 400
    
    # Validation 6: Participant must be a participant
    if participant.role != UserRole.PARTICIPANT:
        return jsonify({'error': 'User is not a participant'}), 400
    
    # Validation 7: Participant must still be solo.
    # Policy: a participant can only be registered in ONE hackathon at a time.
    existing_membership = TeamMember.query.join(Team).filter(TeamMember.user_id == participant_id).first()

    if existing_membership:
        existing_team = existing_membership.team
        if existing_team and existing_team.hackathon_id == hackathon_id:
            return jsonify({'error': 'Participant already in a team for this hackathon'}), 400
        return jsonify({'error': 'Participant already registered in another hackathon'}), 400
    
    # Check for existing pending request
    existing_request = TeamJoinRequest.query.filter_by(
        team_id=team_id,
        user_id=participant_id,
        status='PENDING'
    ).first()
    if existing_request:
        return jsonify({'error': 'Join request already sent'}), 400

    # CREATE REQUEST (NO DIRECT ADD)
    try:
        join_request = TeamJoinRequest(
            team_id=team_id,
            user_id=participant_id,
            requested_by_id=user_id,
            status='PENDING'
        )
        db.session.add(join_request)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Join request sent',
            'request': {
                'id': join_request.id,
                'team_id': team_id,
                'user_id': participant_id
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to send join request', 'details': str(e)}), 500

@api_bp.route('/scan_qr', methods=['POST'])
def scan_qr():
    """
    Handle scan of TEAM QR code (ACCESS or DINNER)
    """
    if session.get('role') not in ['faculty', 'admin']:
         return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    data = request.get_json()
    token = data.get('qr_token')

    if not token:
        return jsonify({'status': 'error', 'message': 'Token missing'}), 400

    # 1. Validate Token
    qr_record = TeamQR.query.filter_by(qr_token=token).first()
    if not qr_record:
        return jsonify({'status': 'error', 'message': 'Invalid QR Token'}), 404

    # 2. Get Context
    team = Team.query.get(qr_record.team_id)
    if not team:
        return jsonify({'status': 'error', 'message': 'Team not found'}), 404
    
    response_data = {
        'team_name': team.name,
        'hackathon': team.hackathon.name,
        'type': qr_record.qr_type
    }

    # 3. Process by Type
    if qr_record.qr_type == 'ACCESS':
        if not getattr(team.hackathon, 'enable_attendance', True):
            return jsonify({'status': 'error', 'message': 'Attendance QR is disabled for this hackathon.', 'data': response_data}), 403

        return jsonify({'status': 'success', 'message': 'Access Granted', 'data': response_data})

    elif qr_record.qr_type in ['BREAKFAST', 'LUNCH', 'DINNER']:
        # Transaction for Daily Count Update
        try:
            today = datetime.utcnow().date()
            
            # Fetch usage for TODAY
            usage = TeamMealUsage.query.filter_by(
                team_id=team.id, 
                meal_type=qr_record.qr_type,
                usage_date=today
            ).with_for_update().first()
            
            # Automatic Reset Logic: If no record for today exists, create it (starting at 0)
            if not usage:
                 usage = TeamMealUsage(
                     team_id=team.id, 
                     meal_type=qr_record.qr_type, 
                     used_count=0,
                     usage_date=today
                 )
                 db.session.add(usage)
            
            member_count = len(team.members)
            
            if usage.used_count < member_count:
                usage.used_count += 1
                usage.last_updated = datetime.utcnow()
                response_data['count'] = f"{usage.used_count}/{member_count}"
                db.session.commit()
                return jsonify({'status': 'success', 'message': f'{qr_record.qr_type} Verified', 'data': response_data})
            else:
                db.session.rollback()
                return jsonify({
                    'status': 'error', 
                    'message': f'Daily Limit Reached ({usage.used_count}/{member_count})',
                    'data': response_data
                }), 400

        except Exception as e:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    return jsonify({'status': 'error', 'message': 'Unknown QR Type'}), 400


@api_bp.route('/analytics/hackathon/<int:hackathon_id>/summary', methods=['GET'])
def analytics_summary(hackathon_id):
    """Chart-ready analytics for Admin dashboards.

    Provides:
    - Registrations (last 7 days): user accounts created (role-based) and team registrations (if teams.created_at exists)
    - Attendance (event day): unique participant check-ins by QRLog on hackathon start date
    - Evaluations (live): per-5-min buckets for last 60 minutes for this hackathon
    """

    if not _admin_only():
        return jsonify({'error': 'Unauthorized'}), 403

    hackathon = Hackathon.query.get_or_404(hackathon_id)
    now = datetime.utcnow()

    # ---------------- Registrations: last 7 days (accounts) ----------------
    # Use actual data range (latest registration) so demo data always appears,
    # and group in Python for cross-database compatibility.

    users = User.query.filter(User.created_at.isnot(None)).all()

    if users:
        all_dates = [u.created_at.date() for u in users]
        ref_day = max(all_dates)
    else:
        ref_day = now.date()

    start_day = ref_day - timedelta(days=6)
    days = [start_day + timedelta(days=i) for i in range(7)]
    day_labels = [d.strftime('%Y-%m-%d') for d in days]

    # User registrations by day (all roles + participants)
    users_by_day = {k: 0 for k in day_labels}
    participants_by_day = {k: 0 for k in day_labels}

    for u in users:
        d = u.created_at.date()
        if start_day <= d <= ref_day:
            key = d.strftime('%Y-%m-%d')
            if key in users_by_day:
                users_by_day[key] += 1
                if u.role == UserRole.PARTICIPANT:
                    participants_by_day[key] += 1

    # Team registrations by day (if teams.created_at exists)
    team_by_day = {k: 0 for k in day_labels}
    try:
        # Some schemas have a teams.created_at column; if present, use it.
        rows = db.session.execute(
            text("SELECT created_at FROM teams WHERE hackathon_id = :hid AND created_at IS NOT NULL"),
            {"hid": hackathon_id},
        ).all()
        for (created_at,) in rows:
            if not created_at:
                continue
            d = created_at.date()
            if start_day <= d <= ref_day:
                key = d.strftime('%Y-%m-%d')
                if key in team_by_day:
                    team_by_day[key] += 1
    except Exception:
        # Older DBs without teams.created_at just won't show team trend line.
        pass

    registrations = {
        'labels': day_labels,
        'series': {
            'accounts_total': [users_by_day[k] for k in day_labels],
            'accounts_participants': [participants_by_day[k] for k in day_labels],
            'teams_registered': [team_by_day[k] for k in day_labels],
        },
        'totals': {
            'accounts_total': sum(users_by_day.values()),
            'accounts_participants': sum(participants_by_day.values()),
            'teams_registered': sum(team_by_day.values()),
        }
    }

    # ---------------- Attendance: event day ----------------
    attendance = {
        'event_date': None,
        'checked_in_unique': 0,
        'checked_in_total_scans': 0,
    }

    if hackathon.start_date:
        event_date = hackathon.start_date.date()
        attendance['event_date'] = event_date.isoformat()
        try:
            # QRLog table stores participant scans (registration/meal).
            # Use ORM/func.date for cross-database compatibility.
            total_scans, unique_participants = (
                db.session.query(
                    func.count(QRLog.id),
                    func.count(func.distinct(QRLog.participant_id)),
                )
                .filter(
                    QRLog.scan_type == 'REGISTRATION',
                    func.date(QRLog.timestamp) == event_date,
                )
                .one()
            )
            attendance['checked_in_total_scans'] = int(total_scans or 0)
            attendance['checked_in_unique'] = int(unique_participants or 0)
        except Exception:
            pass

    # ---------------- Evaluations: live (last 60 min) ----------------
    # Bucket into 5-min intervals for smoother charts.
    # Anchor live window around latest evaluation if available so demo data
    # shows up even when timestamps are not near the current wall-clock time.
    latest_eval = (
        db.session.query(func.max(Evaluation.created_at))
        .filter(Evaluation.hackathon_id == hackathon_id)
        .scalar()
    )
    eval_now = latest_eval or now
    eval_start = eval_now - timedelta(minutes=60)
    buckets = []
    tcur = eval_start.replace(second=0, microsecond=0)
    # Align to 5-min boundary
    tcur = tcur - timedelta(minutes=(tcur.minute % 5))
    while tcur <= eval_now:
        buckets.append(tcur)
        tcur += timedelta(minutes=5)

    bucket_labels = [dt.strftime('%H:%M') for dt in buckets]
    bucket_counts = {dt: 0 for dt in buckets}

    # Fetch evaluations in the window and bucket in Python for portability.
    eval_rows = (
        Evaluation.query
        .filter(
            Evaluation.hackathon_id == hackathon_id,
            Evaluation.created_at.isnot(None),
            Evaluation.created_at >= eval_start,
            Evaluation.created_at <= eval_now,
        )
        .all()
    )

    def _floor_to_5_minutes(dt: datetime) -> datetime:
        minute_block = (dt.minute // 5) * 5
        return dt.replace(minute=minute_block, second=0, microsecond=0)

    for e in eval_rows:
        bdt = _floor_to_5_minutes(e.created_at)
        if bdt in bucket_counts:
            bucket_counts[bdt] += 1

    evaluations_live = {
        'labels': bucket_labels,
        'series': {
            'evaluations_submitted': [bucket_counts[dt] for dt in buckets]
        },
        'totals': {
            'last_60m': sum(bucket_counts.values())
        }
    }

    # ---------------- Live Scan Comparison: today, per hackathon ----------------
    # Derive participants for this hackathon via team memberships and then
    # count their ScanLog entries by access_type for today. This keeps the
    # scan comparison specific to the selected hackathon.

    participant_ids = [
        row[0]
        for row in (
            db.session.query(TeamMember.user_id)
            .join(Team, Team.id == TeamMember.team_id)
            .filter(Team.hackathon_id == hackathon_id)
            .distinct()
            .all()
        )
    ]

    total_participants = len(participant_ids)

    live_scan = {
        'today': now.date().isoformat(),
        'total_participants': total_participants,
        'counts': {k: 0 for k in ['ENTRY', 'BREAKFAST', 'LUNCH', 'DINNER']},
        'percentages': {k: 0.0 for k in ['ENTRY', 'BREAKFAST', 'LUNCH', 'DINNER']},
    }

    if total_participants > 0:
        today = now.date()
        base_q = (
            db.session.query(ScanLog.access_type, func.count(func.distinct(ScanLog.user_id)))
            .filter(
                ScanLog.user_id.in_(participant_ids),
                func.date(ScanLog.scan_time) == today,
            )
            .group_by(ScanLog.access_type)
        )

        for access_type, count in base_q:
            key = str(access_type).upper()
            if key in live_scan['counts']:
                live_scan['counts'][key] = int(count or 0)

        for key, count in live_scan['counts'].items():
            live_scan['percentages'][key] = round((count / total_participants) * 100, 1) if total_participants else 0.0

    return jsonify({
        'hackathon': {
            'id': hackathon.id,
            'name': hackathon.name,
            'status': getattr(hackathon.status, 'value', str(hackathon.status))
        },
        'generated_at': now.isoformat() + 'Z',
        'registrations_last_7d': registrations,
        'attendance_event_day': attendance,
        'evaluations_live': evaluations_live,
        'live_scan_comparison': live_scan,
        'notes': {
            'charts_ui_ready': True,
            'connect_data_when_available': False
        }
    })


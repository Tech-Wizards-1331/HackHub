from flask import jsonify, request, session
from . import api_bp
from app.extensions import db
from app.models import User, Team, TeamMember, Hackathon, HackathonStatus, UserRole, TeamQR, TeamMealUsage
from sqlalchemy import and_
from sqlalchemy import text
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
    
    # Get users who are participants AND not in any team for this hackathon AND is_public = TRUE
    solo_query = db.session.query(User).filter(
        User.role == UserRole.PARTICIPANT,
        User.is_public == True,
        ~User.id.in_(
            db.session.query(TeamMember.user_id).join(Team).filter(
                Team.hackathon_id == hackathon_id
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
    Team leader directly adds a solo participant to their team
    NO approval needed
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
    
    # Validation 7: Participant must still be solo (not in any team for this hackathon)
    existing_membership = TeamMember.query.join(Team).filter(
        and_(
            Team.hackathon_id == hackathon_id,
            TeamMember.user_id == participant_id
        )
    ).first()
    
    if existing_membership:
        return jsonify({'error': 'Participant already in a team'}), 400
    
    # DIRECT ADD (NO APPROVAL)
    try:
        new_member = TeamMember(
            team_id=team_id,
            user_id=participant_id
        )
        db.session.add(new_member)
        
        # Auto-hide: Set is_public to FALSE
        participant.is_public = False
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Participant added to team',
            'member': {
                'id': new_member.id,
                'user_id': participant_id,
                'username': participant.username,
                'full_name': participant.full_name
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to add member', 'details': str(e)}), 500

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
        # Access is always allowed, just log if needed
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
    start_day = (now - timedelta(days=6)).date()
    days = [start_day + timedelta(days=i) for i in range(7)]
    day_labels = [d.strftime('%Y-%m-%d') for d in days]

    # User registrations by day (all roles + participants)
    users_by_day = {k: 0 for k in day_labels}
    participants_by_day = {k: 0 for k in day_labels}

    try:
        rows = db.session.execute(text('''
            SELECT date(created_at) AS d,
                   COUNT(*) AS total,
                   SUM(CASE WHEN role = 'PARTICIPANT' OR role = 'participant' THEN 1 ELSE 0 END) AS participants
            FROM users
            WHERE created_at IS NOT NULL
              AND date(created_at) >= :start_day
            GROUP BY date(created_at)
        '''), {'start_day': start_day.isoformat()}).all()

        for d, total, participants in rows:
            key = str(d)
            if key in users_by_day:
                users_by_day[key] = int(total or 0)
                participants_by_day[key] = int(participants or 0)
    except Exception:
        # If older DB lacks created_at despite migration, keep zeros.
        pass

    # Team registrations by day (if teams.created_at exists)
    team_by_day = {k: 0 for k in day_labels}
    try:
        rows = db.session.execute(text('''
            SELECT date(t.created_at) AS d, COUNT(*) AS total
            FROM teams t
            WHERE t.hackathon_id = :hid
              AND t.created_at IS NOT NULL
              AND date(t.created_at) >= :start_day
            GROUP BY date(t.created_at)
        '''), {'hid': hackathon_id, 'start_day': start_day.isoformat()}).all()
        for d, total in rows:
            key = str(d)
            if key in team_by_day:
                team_by_day[key] = int(total or 0)
    except Exception:
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
            # QRLog table stores participant scans (registration/meal). We count REGISTRATION scans for the event day.
            rows = db.session.execute(text('''
                SELECT
                    COUNT(*) AS total_scans,
                    COUNT(DISTINCT participant_id) AS unique_participants
                FROM qr_logs
                WHERE scan_type = 'REGISTRATION'
                  AND date(timestamp) = :event_date
            '''), {'event_date': event_date.isoformat()}).one()
            attendance['checked_in_total_scans'] = int(rows[0] or 0)
            attendance['checked_in_unique'] = int(rows[1] or 0)
        except Exception:
            pass

    # ---------------- Evaluations: live (last 60 min) ----------------
    # Bucket into 5-min intervals for smoother charts.
    eval_now = now
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

    try:
        rows = db.session.execute(text('''
            SELECT strftime('%Y-%m-%d %H:', created_at) ||
                   printf('%02d', (CAST(strftime('%M', created_at) AS INTEGER) / 5) * 5) AS bucket,
                   COUNT(*) AS total
            FROM evaluations
            WHERE hackathon_id = :hid
              AND created_at IS NOT NULL
              AND datetime(created_at) >= datetime(:eval_start)
            GROUP BY bucket
        '''), {'hid': hackathon_id, 'eval_start': eval_start.strftime('%Y-%m-%d %H:%M:%S')}).all()

        # Map bucket strings back onto our labels
        for bucket_str, total in rows:
            # bucket_str like '2026-01-28 23:10'
            try:
                bdt = datetime.strptime(bucket_str, '%Y-%m-%d %H:%M')
                # Normalize seconds
                bdt = bdt.replace(second=0, microsecond=0)
                if bdt in bucket_counts:
                    bucket_counts[bdt] = int(total or 0)
            except Exception:
                continue
    except Exception:
        pass

    evaluations_live = {
        'labels': bucket_labels,
        'series': {
            'evaluations_submitted': [bucket_counts[dt] for dt in buckets]
        },
        'totals': {
            'last_60m': sum(bucket_counts.values())
        }
    }

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
        'notes': {
            'charts_ui_ready': True,
            'connect_data_when_available': False
        }
    })


from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import faculty_bp
from app.extensions import db
from app.models import (
    User, QRLog, Team, Evaluation, Hackathon, HackathonStatus,
    FacultyAssignment, TeamQR, TeamMealUsage, TeamMember
)
from sqlalchemy import func
from functools import wraps
from datetime import datetime

def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'faculty':
            flash('Faculty access only', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    # Only show hackathons where the faculty is assigned
    assignments = FacultyAssignment.query.filter_by(faculty_id=session['user_id']).all()
    hackathon_ids = [a.hackathon_id for a in assignments]
    hackathons = Hackathon.query.filter(Hackathon.id.in_(hackathon_ids)).all() if hackathon_ids else []
    return render_template('faculty/dashboard.html', hackathons=hackathons)

@faculty_bp.route('/scan_qr', methods=['GET', 'POST'])
@faculty_required
def scan_qr():
    if request.method == 'POST':
        if request.is_json:
            # AJAX/JSON request
            qr_token = request.get_json().get('qr_token')
            
            if not qr_token:
                return jsonify({'status': 'error', 'message': 'Token missing'}), 400
            
            try:
                # Find the QR record
                qr_record = TeamQR.query.filter_by(qr_token=qr_token).first()
                if not qr_record:
                    return jsonify({'status': 'error', 'message': 'Invalid QR Token'}), 404
                
                team = Team.query.get(qr_record.team_id)
                if not team:
                    return jsonify({'status': 'error', 'message': 'Team not found'}), 404
                
                response_data = {
                    'team_name': team.name,
                    'hackathon': team.hackathon.name,
                    'qr_type': qr_record.qr_type
                }
                
                # Process by QR Type
                if qr_record.qr_type == 'ACCESS':
                    # Access - just grant access
                    return jsonify({'status': 'success', 'message': 'Access Granted', 'data': response_data}), 200
                
                elif qr_record.qr_type in ['BREAKFAST', 'LUNCH', 'DINNER']:
                    # Meal QR
                    today = datetime.utcnow().date()
                    usage = TeamMealUsage.query.filter_by(
                        team_id=team.id,
                        meal_type=qr_record.qr_type,
                        usage_date=today
                    ).first()
                    
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
                        return jsonify({'status': 'success', 'message': f'{qr_record.qr_type} Verified', 'data': response_data}), 200
                    else:
                        db.session.rollback()
                        return jsonify({'status': 'error', 'message': f'Daily Limit Reached ({usage.used_count}/{member_count})', 'data': response_data}), 400
                
                return jsonify({'status': 'error', 'message': 'Unknown QR Type'}), 400
                
            except Exception as e:
                db.session.rollback()
                return jsonify({'status': 'error', 'message': str(e)}), 500
        else:
            # Form POST - redirect back
            return redirect(url_for('faculty.scan_qr'))
            
    return render_template('faculty/scan.html')

@faculty_bp.route('/evaluate/<int:hackathon_id>/teams')
@faculty_required
def evaluate_teams_list(hackathon_id):
    # Check assignment
    assignment = FacultyAssignment.query.filter_by(hackathon_id=hackathon_id, faculty_id=session['user_id']).first()
    if not assignment:
        flash("You are not assigned to this hackathon.", "error")
        return redirect(url_for('faculty.dashboard'))
        
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
    # Backend validation: Only allow evaluation when hackathon status is EVALUATION
    if hackathon.status != HackathonStatus.EVALUATION:
        flash("Evaluation is not enabled for this hackathon yet.", "error")
        return redirect(url_for('faculty.dashboard'))
    
    # Get set of team IDs already evaluated by this faculty
    evaluated_teams = db.session.query(Evaluation.team_id).filter_by(
        hackathon_id=hackathon_id, 
        faculty_id=session['user_id']
    ).all()
    evaluated_team_ids = {t[0] for t in evaluated_teams}
    
    return render_template('faculty/evaluate_list.html', 
                           hackathon=hackathon, 
                           teams=hackathon.teams, 
                           evaluated_team_ids=evaluated_team_ids,
                           is_locked=(hackathon.status == HackathonStatus.RESULT_PUBLISHED))

@faculty_bp.route('/evaluate/team/<int:team_id>', methods=['GET', 'POST'])
@faculty_required
def evaluate_team(team_id):
    team = Team.query.get_or_404(team_id)
    
    # Check if faculty is assigned to this hackathon
    assignment = FacultyAssignment.query.filter_by(hackathon_id=team.hackathon_id, faculty_id=session['user_id']).first()
    if not assignment:
        flash("You are not assigned to evaluate this hackathon.", "error")
        return redirect(url_for('faculty.dashboard'))
    
    # Backend validation: Only allow evaluation when hackathon status is EVALUATION
    if team.hackathon.status != HackathonStatus.EVALUATION:
        flash("Evaluation is not enabled for this hackathon yet.", "error")
        return redirect(url_for('faculty.dashboard'))

    if team.hackathon.status == HackathonStatus.RESULT_PUBLISHED:
        flash("Evaluations are locked.", "error")
        return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))
    
    if request.method == 'POST':
        existing_eval = Evaluation.query.filter_by(team_id=team_id, faculty_id=session['user_id']).first()
        if existing_eval:
            flash("You have already evaluated this team.", "error")
            return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))

        try:
            innovation = int(request.form.get('innovation_score'))
            technical = int(request.form.get('technical_score'))
            uiux = int(request.form.get('uiux_score'))
            practicality = int(request.form.get('practicality_score'))
            presentation = int(request.form.get('presentation_score'))

            if any(score < 0 or score > 10 for score in [innovation, technical, uiux, practicality, presentation]):
                raise ValueError("Scores must be 0-10")

            total_score = innovation + technical + uiux + practicality + presentation

            evaluation = Evaluation(
                hackathon_id=team.hackathon_id,
                team_id=team.id,
                faculty_id=session['user_id'],
                stage_id=1,
                score=float(total_score),
                innovation_score=innovation,
                technical_score=technical,
                uiux_score=uiux,
                practicality_score=practicality,
                presentation_score=presentation,
                total_score=total_score
            )
            db.session.add(evaluation)
            db.session.commit()
            flash("Evaluation submitted", "success")
            return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))
            
        except ValueError:
            flash("Invalid scores. Must be integers 0-10.", "error")
            
    return render_template('faculty/evaluate_form.html', team=team)


@faculty_bp.route('/team-explorer')
@faculty_required
def team_explorer_page():
    """
    Faculty Team Explorer: view teams for hackathons they are assigned to.
    Reuses the admin template but pre-filters hackathons server-side.
    """
    assignment_records = FacultyAssignment.query.filter_by(faculty_id=session['user_id']).all()
    hackathon_ids = [a.hackathon_id for a in assignment_records]
    hackathons = Hackathon.query.filter(Hackathon.id.in_(hackathon_ids)).order_by(Hackathon.start_date.desc().nullslast()).all() if hackathon_ids else []
    return render_template('faculty/team_explorer.html', hackathons=hackathons)


@faculty_bp.route('/hackathon/<int:hackathon_id>/teams')
@faculty_required
def hackathon_teams_api(hackathon_id):
    """
    API: GET /faculty/hackathon/<hackathon_id>/teams
    Returns team data ONLY if the faculty is assigned to this hackathon.
    Query params: page, per_page, search (same as admin).
    """
    # Enforce: faculty must be assigned to this hackathon
    assignment = FacultyAssignment.query.filter_by(
        hackathon_id=hackathon_id,
        faculty_id=session['user_id'],
    ).first()
    if not assignment:
        return jsonify({'error': 'Access denied: you are not assigned to this hackathon'}), 403

    hackathon = Hackathon.query.get_or_404(hackathon_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str).strip()

    teams_query = db.session.query(Team).filter(Team.hackathon_id == hackathon_id)

    if search:
        like_pattern = f'%{search}%'
        matching_team_ids = (
            db.session.query(TeamMember.team_id)
            .join(User, TeamMember.user_id == User.id)
            .join(Team, TeamMember.team_id == Team.id)
            .filter(
                Team.hackathon_id == hackathon_id,
                db.or_(
                    User.full_name.ilike(like_pattern),
                    User.email.ilike(like_pattern),
                    User.username.ilike(like_pattern),
                    Team.name.ilike(like_pattern),
                )
            )
            .distinct()
            .subquery()
        )
        teams_query = teams_query.filter(Team.id.in_(db.session.query(matching_team_ids.c.team_id)))

    total_teams_count = teams_query.count()

    total_users_count = (
        db.session.query(func.count(TeamMember.id))
        .join(Team, TeamMember.team_id == Team.id)
        .filter(Team.hackathon_id == hackathon_id)
        .scalar()
    ) or 0

    paginated_teams = (
        teams_query
        .order_by(Team.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    teams_data = []
    for team in paginated_teams:
        members = (
            db.session.query(TeamMember, User)
            .join(User, TeamMember.user_id == User.id)
            .filter(TeamMember.team_id == team.id)
            .all()
        )
        member_list = []
        for tm, user in members:
            member_list.append({
                'name': user.full_name or user.username,
                'email': user.email,
                'college': user.college or '—',
                'registration_id': user.id,
                'is_present': bool(user.is_present) if user.is_present is not None else False,
            })

        teams_data.append({
            'team_id': team.id,
            'team_name': team.name,
            'member_count': len(member_list),
            'is_closed': team.is_closed,
            'members': member_list,
        })

    total_pages = max(1, -(-total_teams_count // per_page))

    return jsonify({
        'hackathon_id': hackathon.id,
        'hackathon_name': hackathon.name,
        'total_users': total_users_count,
        'total_teams': total_teams_count,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'teams': teams_data,
    })

from flask import render_template, request, redirect, url_for, flash, session, current_app, jsonify
from . import admin_bp
from app.extensions import db
from app.models import (
    Hackathon, HackathonStatus, ProblemStatement, Evaluation,
    EvaluationCriteria, User, UserRole, FacultyAssignment, ScanLog,
    Team, TeamMember
)
from app.utils.hackathon_lifecycle import sync_hackathon_status
from app.utils.problem_selection import auto_assign_problems
from functools import wraps
from datetime import datetime
from werkzeug.utils import secure_filename
from sqlalchemy import func
import os
import uuid

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'pdf'}

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access only', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    hackathons = Hackathon.query.all()
    stats = {}
    for h in hackathons:
        stats[h.id] = {
            'teams': len(h.teams)
        }
    
    # --- Scan Statistics ---
    real_participant_count = User.query.filter_by(role=UserRole.PARTICIPANT).count()
    total_participants = real_participant_count if real_participant_count > 0 else 1

    scan_counts = {
        'ENTRY': ScanLog.query.filter_by(access_type='ENTRY').count(),
        'BREAKFAST': ScanLog.query.filter_by(access_type='BREAKFAST').count(),
        'LUNCH': ScanLog.query.filter_by(access_type='LUNCH').count(),
        'DINNER': ScanLog.query.filter_by(access_type='DINNER').count(),
    }

    scan_stats = {
        'total_participants': real_participant_count,
        'counts': scan_counts,
        'percentages': {
            'ENTRY': round((scan_counts['ENTRY'] / total_participants) * 100, 1),
            'BREAKFAST': round((scan_counts['BREAKFAST'] / total_participants) * 100, 1),
            'LUNCH': round((scan_counts['LUNCH'] / total_participants) * 100, 1),
            'DINNER': round((scan_counts['DINNER'] / total_participants) * 100, 1),
        }
    }

    return render_template('admin/dashboard.html', hackathons=hackathons, stats=stats, scan_stats=scan_stats)

@admin_bp.route('/create_hackathon', methods=['GET', 'POST'])
@admin_required
def create_hackathon():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        venue = request.form.get('venue', '').strip()
        max_teams = request.form.get('max_teams')
        min_team_size = request.form.get('min_team_size')
        max_team_size = request.form.get('max_team_size')
        registration_open_date = datetime.strptime(request.form.get('registration_open_date'), '%Y-%m-%dT%H:%M')
        registration_close_str = request.form.get('registration_close_date')
        registration_close_date = None
        if registration_close_str:
            registration_close_date = datetime.strptime(registration_close_str, '%Y-%m-%dT%H:%M')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
        
        end_date_str = request.form.get('end_date')
        end_date = None
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')

        if registration_close_date and registration_open_date > registration_close_date:
            flash('Registration open date must be before registration close date.', 'error')
            return redirect(url_for('admin.create_hackathon'))

        if registration_close_date and registration_close_date > start_date:
            flash('Registration close date must be on or before the hackathon start date.', 'error')
            return redirect(url_for('admin.create_hackathon'))

        if end_date and end_date < start_date:
            flash('Hackathon end date must be after the start date.', 'error')
            return redirect(url_for('admin.create_hackathon'))
        
        # Meal Config
        enable_breakfast = 'enable_breakfast' in request.form
        enable_lunch = 'enable_lunch' in request.form
        enable_dinner = 'enable_dinner' in request.form
        
        # Meal times (HH:MM format)
        breakfast_time = request.form.get('breakfast_time', '')  # e.g., "07:00"
        lunch_time = request.form.get('lunch_time', '')          # e.g., "12:30"
        dinner_time = request.form.get('dinner_time', '')        # e.g., "18:00"
        
        hackathon = Hackathon(
            name=name,
            description=description,
            venue=venue if venue else None,
            max_teams=max_teams,
            min_team_size=min_team_size,
            max_team_size=max_team_size,
            registration_open_date=registration_open_date,
            registration_close_date=registration_close_date,
            start_date=start_date,
            end_date=end_date,
            enable_breakfast=enable_breakfast,
            enable_lunch=enable_lunch,
            enable_dinner=enable_dinner,
            breakfast_time=breakfast_time if enable_breakfast else None,
            lunch_time=lunch_time if enable_lunch else None,
            dinner_time=dinner_time if enable_dinner else None,
        )
        sync_hackathon_status(hackathon)
        db.session.add(hackathon)
        db.session.commit()
        flash('Hackathon created', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/hackathon_create.html')

@admin_bp.route('/hackathon/<int:id>/manage', methods=['GET', 'POST'])
@admin_required
def manage_hackathon(id):
    hackathon = Hackathon.query.get_or_404(id)
    if request.method == 'POST':
        # Status Update / Auto-Assign Trigger
        status_str = request.form.get('status')
        action = request.form.get('action')
        
        if action == 'auto_assign':
            result = auto_assign_problems(id)
            if result['status'] == 'success':
                flash(f"Auto-assign complete. Assigned {result['assigned']} teams.", 'success')
            else:
                flash(f"Auto-assign failed: {result['message']}", 'error')
        
        elif action == 'update_meals':
            hackathon.enable_breakfast = 'enable_breakfast' in request.form
            hackathon.enable_lunch = 'enable_lunch' in request.form
            hackathon.enable_dinner = 'enable_dinner' in request.form
            
            # Update meal times (HH:MM format)
            hackathon.breakfast_time = request.form.get('breakfast_time') if hackathon.enable_breakfast else None
            hackathon.lunch_time = request.form.get('lunch_time') if hackathon.enable_lunch else None
            hackathon.dinner_time = request.form.get('dinner_time') if hackathon.enable_dinner else None
            
            db.session.commit()
            flash('Meal configuration updated', 'success')

        elif action == 'update_attendance':
            hackathon.enable_attendance = 'enable_attendance' in request.form
            db.session.commit()
            flash('Attendance QR configuration updated', 'success')

        elif status_str:
            hackathon.status = HackathonStatus[status_str]
            db.session.commit()
            flash('Status updated', 'success')
    
    # Fetch current criteria configuration
    current_criteria = EvaluationCriteria.query.filter_by(hackathon_id=id).all()
    # Convert to dictionary for easy lookup in template: {'Innovation': 30, ...}
    criteria_map = {c.name: c.percentage for c in current_criteria if c.is_enabled}
            
    return render_template('admin/hackathon_manage.html', hackathon=hackathon, HackathonStatus=HackathonStatus, criteria_map=criteria_map)

@admin_bp.route('/hackathon/<int:id>/add_stage', methods=['POST'])
@admin_bp.route('/hackathon/<int:id>/problems/upload', methods=['POST'])
@admin_required
def upload_problem_statement(id):
    hackathon = Hackathon.query.get_or_404(id)
    
    if 'pdf_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('admin.manage_hackathon', id=id))
        
    file = request.files['pdf_file']
    title = request.form.get('title')
    max_teams = request.form.get('max_teams', 50) # default or form value
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('admin.manage_hackathon', id=id))
        
    if file and allowed_file(file.filename):
        # Secure filename and prevent overwrite
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        
        # Determine upload path
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'problem_statements')
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        file_path = os.path.join(upload_dir, unique_filename)
        file.save(file_path)
        
        # Save relative path to DB
        db_path = f"uploads/problem_statements/{unique_filename}"
        
        problem = ProblemStatement(
            hackathon_id=id,
            title=title,
            pdf_file_path=db_path,
            max_team_limit=max_teams
        )
        
        db.session.add(problem)
        db.session.commit()
        flash('Problem Statement uploaded successfully', 'success')
    else:
        flash('Invalid file type. Only PDF allowed.', 'error')
        
    return redirect(url_for('admin.manage_hackathon', id=id))

@admin_bp.route('/results/<int:hackathon_id>', methods=['GET', 'POST'])
@admin_required
def results(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)

    if request.method == 'POST':
        hackathon.status = HackathonStatus.RESULT_PUBLISHED
        db.session.commit()
        flash("Results published successfully. Evaluations locked.", "success")
        return redirect(url_for('admin.results', hackathon_id=hackathon.id))
        
    teams = hackathon.teams
    results_data = []
    
    for team in teams:
        evals = Evaluation.query.filter_by(team_id=team.id).all()
        if evals:
            # Average of all faculty scores.
            # Supports both new schema (`total_score`) and legacy schema (`score`).
            scores = []
            for e in evals:
                val = getattr(e, 'total_score', None)
                if val is None:
                    val = getattr(e, 'score', None)
                if val is not None:
                    scores.append(float(val))
            avg_score = (sum(scores) / len(scores)) if scores else 0
        else:
            avg_score = 0
            
        results_data.append({
            'team_id': team.id,
            'name': team.name,
            'score': round(avg_score, 2)
        })
        
    results_data.sort(key=lambda x: x['score'], reverse=True)
    
    return render_template('admin/results.html', hackathon=hackathon, results=results_data)

@admin_bp.route('/evaluation-config/<int:hackathon_id>', methods=['POST'])
@admin_required
def evaluation_config(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
    data = request.get_json()
    if not data:
        return {'status': 'error', 'message': 'Invalid JSON Payload'}, 400
        
    valid_names = ['Innovation', 'Technical Skills', 'UI/UX', 'Practical Use', 'Presentation']
    new_criteria = []
    total_percentage = 0.0
    
    for item in data:
        name = item.get('name')
        if name not in valid_names:
            continue
            
        try:
            percentage = float(item.get('percentage', 0))
            if percentage < 0 or percentage > 100:
                raise ValueError
        except:
            return {'status': 'error', 'message': f'Invalid percentage for {name}'}, 400
            
        new_criteria.append({
            'name': name,
            'percentage': percentage,
            'is_enabled': True
        })
        total_percentage += percentage
            
    if abs(total_percentage - 100.0) > 0.01:
        return {'status': 'error', 'message': f'Total percentage must be exactly 100%. Current: {total_percentage}%'}, 400
        
    # Save config
    EvaluationCriteria.query.filter_by(hackathon_id=hackathon_id).delete()
    
    for c in new_criteria:
        crit = EvaluationCriteria(
            hackathon_id=hackathon_id,
            name=c['name'],
            percentage=c['percentage'],
            is_enabled=True
        )
        db.session.add(crit)
        
    db.session.commit()
    return {'status': 'success', 'message': 'Configuration saved successfully.'}

@admin_bp.route('/faculty', methods=['GET'])
@admin_required
def list_faculty():
    # Returns list of all faculty
    faculty_members = User.query.filter_by(role=UserRole.FACULTY).all()
    return {
        'faculty': [{
            'id': f.id,
            'name': f.full_name,
            'email': f.email,
            'college': f.college
        } for f in faculty_members]
    }

@admin_bp.route('/hackathons/<int:hackathon_id>/assigned-faculty', methods=['GET'])
@admin_required
def get_assigned_faculty(hackathon_id):
    # Returns faculty already assigned
    assignments = FacultyAssignment.query.filter_by(hackathon_id=hackathon_id).all()
    assigned_data = []
    for a in assignments:
        faculty = User.query.get(a.faculty_id)
        if faculty:
            assigned_data.append({
                'id': faculty.id,
                'name': faculty.full_name,
                'email': faculty.email,
                'assignment_id': a.id,
                'assigned_at': a.assigned_at.isoformat() if a.assigned_at else None
            })
    return {'assigned_faculty': assigned_data}

@admin_bp.route('/hackathons/<int:hackathon_id>/assign-faculty', methods=['POST'])
@admin_required
def assign_faculty(hackathon_id):
    # Body: faculty_id
    # Assign faculty to hackathon
    data = request.get_json()
    if not data or 'faculty_id' not in data:
        return {'status': 'error', 'message': 'Missing faculty_id'}, 400
        
    try:
        faculty_id = int(data.get('faculty_id'))
    except (ValueError, TypeError):
        return {'status': 'error', 'message': 'Invalid faculty_id format'}, 400

    # Validation
    hackathon = Hackathon.query.get(hackathon_id)
    if not hackathon:
        return {'status': 'error', 'message': 'Hackathon not found'}, 404
        
    faculty = User.query.get(faculty_id)
    if not faculty or faculty.role != UserRole.FACULTY:
        return {'status': 'error', 'message': 'Invalid faculty user'}, 400
        
    # Check duplicate
    existing = FacultyAssignment.query.filter_by(hackathon_id=hackathon_id, faculty_id=faculty_id).first()
    if existing:
        return {'status': 'error', 'message': 'Faculty already assigned to this hackathon'}, 400
        
    assignment = FacultyAssignment(hackathon_id=hackathon_id, faculty_id=faculty_id)
    db.session.add(assignment)
    db.session.commit()
    
    return {'status': 'success', 'message': 'Faculty assigned successfully'}

@admin_bp.route('/hackathons/<int:hackathon_id>/remove-faculty/<int:faculty_id>', methods=['DELETE'])
@admin_required
def remove_faculty_assignment(hackathon_id, faculty_id):
    # Unassign faculty
    assignment = FacultyAssignment.query.filter_by(hackathon_id=hackathon_id, faculty_id=faculty_id).first()
    if not assignment:
        return {'status': 'error', 'message': 'Assignment not found'}, 404
        
    db.session.delete(assignment)
    db.session.commit()
    
    return {'status': 'success', 'message': 'Faculty unassigned successfully'}


# ─── Hackathon Teams Explorer ───────────────────────────────────────────────

@admin_bp.route('/hackathon-teams')
@admin_required
def hackathon_teams_page():
    """Render the hackathon teams explorer page."""
    hackathons = Hackathon.query.order_by(Hackathon.id.desc()).all()
    return render_template('admin/hackathon_teams.html', hackathons=hackathons)


@admin_bp.route('/hackathon/<int:hackathon_id>/teams')
@admin_required
def hackathon_teams_api(hackathon_id):
    """
    API: GET /admin/hackathon/<hackathon_id>/teams
    Returns team-wise grouped participant data with pagination and search.
    Query params:
        page (int)   – page number (default 1)
        per_page (int) – teams per page (default 20)
        search (str) – filter by member name or email
    """
    hackathon = Hackathon.query.get_or_404(hackathon_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str).strip()

    # Base query: teams belonging to the selected hackathon
    teams_query = (
        db.session.query(Team)
        .filter(Team.hackathon_id == hackathon_id)
    )

    # If search term: only include teams that have at least one matching member
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

    # Total registered users across all teams in this hackathon
    total_users_count = (
        db.session.query(func.count(TeamMember.id))
        .join(Team, TeamMember.team_id == Team.id)
        .filter(Team.hackathon_id == hackathon_id)
        .scalar()
    ) or 0

    # Pagination
    paginated_teams = (
        teams_query
        .order_by(Team.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Build response with eager-loaded members
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

    total_pages = max(1, -(-total_teams_count // per_page))  # ceil division

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

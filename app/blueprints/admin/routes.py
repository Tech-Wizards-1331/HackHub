from flask import render_template, request, redirect, url_for, flash, session, current_app
from . import admin_bp
from app.extensions import db
from app.models import Hackathon, HackathonStatus, ProblemStatement, Evaluation, EvaluationCriteria, User, UserRole, FacultyAssignment
from app.utils.problem_selection import auto_assign_problems
from functools import wraps
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'pdf'}

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access only')
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
    return render_template('admin/dashboard.html', hackathons=hackathons, stats=stats)

@admin_bp.route('/create_hackathon', methods=['GET', 'POST'])
@admin_required
def create_hackathon():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        max_teams = request.form.get('max_teams')
        min_team_size = request.form.get('min_team_size')
        max_team_size = request.form.get('max_team_size')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
        
        end_date_str = request.form.get('end_date')
        end_date = None
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        
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
            max_teams=max_teams,
            min_team_size=min_team_size,
            max_team_size=max_team_size,
            start_date=start_date,
            end_date=end_date,
            enable_breakfast=enable_breakfast,
            enable_lunch=enable_lunch,
            enable_dinner=enable_dinner,
            breakfast_time=breakfast_time if enable_breakfast else None,
            lunch_time=lunch_time if enable_lunch else None,
            dinner_time=dinner_time if enable_dinner else None,
        )
        db.session.add(hackathon)
        db.session.commit()
        flash('Hackathon created')
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

        elif status_str:
            hackathon.status = HackathonStatus[status_str]
            db.session.commit()
            flash('Status updated')
    
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
        flash('No file part')
        return redirect(url_for('admin.manage_hackathon', id=id))
        
    file = request.files['pdf_file']
    title = request.form.get('title')
    max_teams = request.form.get('max_teams', 50) # default or form value
    
    if file.filename == '':
        flash('No selected file')
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
        flash('Problem Statement uploaded successfully')
    else:
        flash('Invalid file type. Only PDF allowed.')
        
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

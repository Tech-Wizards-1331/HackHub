from flask import render_template, request, redirect, url_for, flash, session, current_app
from . import admin_bp
from app.extensions import db
from app.models import Hackathon, HackathonStatus, Stage, ProblemStatement
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
            'teams': len(h.teams),
            'stages': len(h.stages)
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
        
        hackathon = Hackathon(
            name=name, 
            description=description,
            max_teams=max_teams,
            min_team_size=min_team_size,
            max_team_size=max_team_size,
            start_date=start_date
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
                
        elif status_str:
            hackathon.status = HackathonStatus[status_str]
            db.session.commit()
            flash('Status updated')
            
    return render_template('admin/hackathon_manage.html', hackathon=hackathon, HackathonStatus=HackathonStatus)

@admin_bp.route('/hackathon/<int:id>/add_stage', methods=['POST'])
@admin_required
def add_stage(id):
    name = request.form.get('name')
    weightage = float(request.form.get('weightage'))
    
    stage = Stage(hackathon_id=id, name=name, weightage=weightage)
    db.session.add(stage)
    db.session.commit()
    return redirect(url_for('admin.manage_hackathon', id=id))

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

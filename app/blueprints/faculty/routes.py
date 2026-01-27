from flask import render_template, request, session, redirect, url_for, flash
from . import faculty_bp
from app.extensions import db
from app.models import User, QRLog, Team, Evaluation, Hackathon, HackathonStatus, FacultyAssignment
from functools import wraps

def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'faculty':
            flash('Faculty access only')
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
        qr_data = request.form.get('qr_data')
        scan_type = request.form.get('scan_type')
        
        try:
            # Expected format: PARTICIPANT-123
            if not qr_data.startswith('PARTICIPANT-'):
                raise ValueError("Invalid Format")
                
            p_id = int(qr_data.split('-')[1])
            participant = User.query.get(p_id)
            if not participant:
                flash("Participant not found", "error")
                return redirect(url_for('faculty.scan_qr'))
                
            if scan_type == 'REGISTRATION':
                if participant.is_present:
                    flash(f"{participant.full_name} is already marked PRESENT", "warning")
                else:
                    participant.is_present = True
                    log = QRLog(participant_id=p_id, scanned_by_id=session['user_id'], scan_type='REGISTRATION', details="Check-in")
                    db.session.add(log)
                    db.session.commit()
                    flash(f"{participant.full_name} marked PRESENT successfully", "success")
                    
            elif scan_type == 'MEAL':
                if not participant.is_present:
                    flash(f"Cannot scan meal. {participant.full_name} has not checked in!", "error")
                else:
                    # Check for duplicates? For now, allow multiple provided it's logged
                    log = QRLog(participant_id=p_id, scanned_by_id=session['user_id'], scan_type='MEAL', details="Meal Scan")
                    db.session.add(log)
                    db.session.commit()
                    flash(f"Meal scanned for {participant.full_name}", "success")
                    
        except Exception as e:
            flash(f"Error scanning: {str(e)}", "error")
            
    return render_template('faculty/scan.html')

@faculty_bp.route('/evaluate/<int:hackathon_id>/teams')
@faculty_required
def evaluate_teams_list(hackathon_id):
    # Check assignment
    assignment = FacultyAssignment.query.filter_by(hackathon_id=hackathon_id, faculty_id=session['user_id']).first()
    if not assignment:
        flash("You are not assigned to this hackathon.")
        return redirect(url_for('faculty.dashboard'))
        
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
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
            
            if any(score < 0 or score > 10 for score in [innovation, technical, uiux, practicality]):
                raise ValueError("Scores must be 0-10")
                
            total_score = innovation + technical + uiux + practicality
            
            evaluation = Evaluation(
                hackathon_id=team.hackathon_id,
                team_id=team.id,
                faculty_id=session['user_id'],
                innovation_score=innovation,
                technical_score=technical,
                uiux_score=uiux,
                practicality_score=practicality,
                total_score=total_score
            )
            db.session.add(evaluation)
            db.session.commit()
            flash("Evaluation submitted")
            return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))
            
        except ValueError:
            flash("Invalid scores. Must be integers 0-10.", "error")
            
    return render_template('faculty/evaluate_form.html', team=team)

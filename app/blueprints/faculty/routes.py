from flask import render_template, request, session, redirect, url_for, flash
from . import faculty_bp
from app.extensions import db
from app.models import User, QRLog, Team, Evaluation, Stage, Hackathon
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
    # Show all hackathons for simplicity in this demo, or filter by assignment
    hackathons = Hackathon.query.all()
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
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    return render_template('faculty/evaluate_list.html', hackathon=hackathon, teams=hackathon.teams)

@faculty_bp.route('/evaluate/team/<int:team_id>', methods=['GET', 'POST'])
@faculty_required
def evaluate_team(team_id):
    team = Team.query.get_or_404(team_id)
    stages = team.hackathon.stages
    
    # Fairness Check: College Conflict
    faculty = User.query.get(session['user_id'])
    for member in team.members:
        # Assuming we can access member.user.college. 
        # (Need to ensure User relationship is loaded or via join)
        if member.user.college and faculty.college and member.user.college.lower() == faculty.college.lower():
            flash(f"Conflict of Interest: Team member {member.user.username} is from your college ({faculty.college}). Calculation disabled.", "error")
            return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))
    
    if request.method == 'POST':
        stage_id = request.form.get('stage_id')
        score = request.form.get('score')
        comments = request.form.get('comments')
        
        # Check if already evaluated for this stage?
        
        eval = Evaluation(team_id=team.id, faculty_id=session['user_id'], stage_id=stage_id, score=score, comments=comments)
        db.session.add(eval)
        db.session.commit()
        flash("Evaluation submitted")
        return redirect(url_for('faculty.evaluate_teams_list', hackathon_id=team.hackathon_id))
        
    return render_template('faculty/evaluate_form.html', team=team, stages=stages)

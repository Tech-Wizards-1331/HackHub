from flask import render_template, request, session, redirect, url_for, flash
from . import participant_bp
from app.extensions import db
from app.models import Hackathon, Team, TeamMember, User, HackathonStatus, ProblemStatement, TeamQR
from flask import jsonify, current_app
from app.utils.qr_manager import generate_team_qrs
from functools import wraps
import uuid

def participant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'participant':
            flash('Participant access only')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@participant_bp.route('/dashboard')
@participant_required
def dashboard():
    user_id = session.get('user_id')
    # Use join to get team details
    my_memberships = TeamMember.query.filter_by(user_id=user_id).all()
    
    open_hackathons = Hackathon.query.filter_by(status=HackathonStatus.REGISTRATION_OPEN).all()
    
    return render_template('participant/dashboard.html', 
                           my_memberships=my_memberships, 
                           open_hackathons=open_hackathons)

@participant_bp.route('/hackathon/<int:hackathon_id>/register', methods=['GET', 'POST'])
@participant_required
def register_hackathon(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = session['user_id']
        
        # Check if already in a team for this hackathon
        existing = TeamMember.query.join(Team).filter(Team.hackathon_id==hackathon_id, TeamMember.user_id==user_id).first()
        if existing:
            flash("You are already registered for this hackathon")
            return redirect(url_for('participant.dashboard'))
        
        if action == 'create_team':
            team_name = request.form.get('team_name')
            team = Team(name=team_name, hackathon_id=hackathon.id, leader_id=user_id)
            db.session.add(team)
            db.session.commit()
            
            member = TeamMember(team_id=team.id, user_id=user_id)
            db.session.add(member)
            db.session.commit()

            # Generate QRs
            try:
                generate_team_qrs(team.id)
            except Exception as e:
                print(f"QR Generation failed: {e}")
            
            flash(f"Team created successfully!")
            return redirect(url_for('participant.dashboard'))
                
    return render_template('participant/hackathon_register.html', hackathon=hackathon)

@participant_bp.route('/team/<int:team_id>')
@participant_required
def view_team(team_id):
    team = Team.query.get_or_404(team_id)
    # Security: check membership
    is_member = TeamMember.query.filter_by(team_id=team.id, user_id=session['user_id']).first()
    if not is_member:
        flash("Access Denied")
        return redirect(url_for('participant.dashboard'))
    
    # Filter available problems: Only those not selected by ANY team
    available_problems = []
    if team.hackathon.status == HackathonStatus.PROBLEM_SELECTION:
        all_problems = ProblemStatement.query.filter_by(hackathon_id=team.hackathon_id).all()
        # "Show only problems NOT selected by any team"
        available_problems = [p for p in all_problems if len(p.teams) == 0]
        
    return render_template('participant/team_view.html', team=team, available_problems=available_problems)

@participant_bp.route('/team/problem', methods=['GET'])
@participant_required
def get_team_problem():
    user_id = session['user_id']
    team_id = request.args.get('team_id')
    
    if not team_id:
        return jsonify({'error': 'team_id required'}), 400
        
    team = Team.query.get(team_id)
    if not team:
        return jsonify({'error': 'Team not found'}), 404
        
    # Check membership
    if not any(m.user_id == user_id for m in team.members):
        return jsonify({'error': 'Unauthorized'}), 403
        
    if team.problem_statement:
        return jsonify({
            'status': 'success',
            'problem': {
                'id': team.problem_statement.id,
                'title': team.problem_statement.title,
                'pdf_url': url_for('static', filename=team.problem_statement.pdf_file_path)
            }
        })
    
    return jsonify({'status': 'none', 'message': 'No problem selected'})

@participant_bp.route('/team/<int:team_id>/member/<int:member_id>/remove')
@participant_required
def remove_member(team_id, member_id):
    team = Team.query.get_or_404(team_id)
    if team.leader_id != session['user_id']:
        return "Unauthorized"
        
    member = TeamMember.query.get_or_404(member_id)
    user = User.query.get(member.user_id)
    if user:
        user.is_public = False
    db.session.delete(member)
    db.session.commit()
    return redirect(url_for('participant.view_team', team_id=team.id))

@participant_bp.route('/hackathon/<int:hackathon_id>/find_teams')
@participant_required
def find_teams(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    # Logic: Show teams that are not closed
    teams = Team.query.filter_by(hackathon_id=hackathon_id, is_closed=False).all()
    return render_template('participant/team_find.html', hackathon=hackathon, teams=teams)

@participant_bp.route('/hackathon/<int:hackathon_id>/team/<int:team_id>/find_members')
@participant_required
def find_members(hackathon_id, team_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    team = Team.query.get_or_404(team_id)
    
    # Security: only team leader
    if team.leader_id != session['user_id']:
        flash('Only team leader can find members')
        return redirect(url_for('participant.view_team', team_id=team_id))
    
    return render_template('participant/team_find.html', hackathon=hackathon, team=team)

@participant_bp.route('/hackathon/<int:hackathon_id>/solo_register', methods=['POST'])
@participant_required
def solo_register(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)
    
    # Check if already in a team for this hackathon
    existing = TeamMember.query.join(Team).filter(Team.hackathon_id==hackathon_id, TeamMember.user_id==user_id).first()
    if existing:
        return {'error': 'Already in a team'}, 400
    
    skills = request.form.get('skills', '')
    user.skills = skills
    user.is_public = True
    
    db.session.commit()
    
    flash('Profile updated. You are now visible to team leaders.')
    return redirect(url_for('participant.dashboard'))

@participant_bp.route('/team/<int:team_id>/qr-codes', methods=['GET'])
@participant_required
def get_team_qrs(team_id):
    """
    Get ACCESS and DINNER QRs for the team
    Restricted to Team Leader (or team members?) 
    User said "Team Leader UI", so strict check.
    """
    team = Team.query.get_or_404(team_id)
    user_id = session['user_id']
    
    # 1. Security Check
    if team.leader_id != user_id:
        return jsonify({'error': 'Unauthorized: Only Team Leader can access QRs'}), 403
    
    # 2. Ensure QRs exist (Lazy Generation)
    # If Admin enabled a new meal type after team creation, this generates it now.
    try:
        generate_team_qrs(team.id)
    except Exception as e:
        current_app.logger.error(f"QR Gen Error: {e}")
    
    # 3. Fetch & Filter QRs
    # Only show QRs that are CURRENTLY enabled in hackathon config
    allowed_types = {'ACCESS'}
    if team.hackathon.enable_breakfast: allowed_types.add('BREAKFAST')
    if team.hackathon.enable_lunch: allowed_types.add('LUNCH')
    if team.hackathon.enable_dinner: allowed_types.add('DINNER')

    qrs = TeamQR.query.filter_by(team_id=team_id).all()
    
    results = []
    for qr in qrs:
        if qr.qr_type in allowed_types:
            filename = f"team_{team.id}_{qr.qr_type}_{qr.qr_token[:8]}.png"
            file_url = url_for('static', filename=f"qrcodes/teams/{filename}")
            
            results.append({
                'type': qr.qr_type,
                'url': file_url,
                'download_name': f"{team.name}_{qr.qr_type}_QR.png"
            })
        
    return jsonify({
        'status': 'success',
        'team_name': team.name,
        'qrs': results
    })


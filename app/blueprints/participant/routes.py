from flask import render_template, request, session, redirect, url_for, flash
from . import participant_bp
from app.extensions import db
from app.models import Hackathon, Team, TeamMember, User, HackathonStatus
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
            access_code = str(uuid.uuid4())[:8]
            team = Team(name=team_name, hackathon_id=hackathon.id, leader_id=user_id, access_code=access_code)
            db.session.add(team)
            db.session.commit()
            
            member = TeamMember(team_id=team.id, user_id=user_id, status='accepted')
            db.session.add(member)
            db.session.commit()
            
            flash(f"Team created! Access Code: {access_code}")
            return redirect(url_for('participant.dashboard'))
            
        elif action == 'join_team':
            access_code = request.form.get('access_code')
            team = Team.query.filter_by(access_code=access_code, hackathon_id=hackathon.id).first()
            if team:
                member = TeamMember(team_id=team.id, user_id=user_id, status='pending')
                db.session.add(member)
                db.session.commit()
                flash("Join request sent")
                return redirect(url_for('participant.dashboard'))
            else:
                flash("Invalid access code")
                
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
        
    return render_template('participant/team_view.html', team=team)

@participant_bp.route('/team/<int:team_id>/member/<int:member_id>/<action>')
@participant_required
def manage_member(team_id, member_id, action):
    team = Team.query.get_or_404(team_id)
    if team.leader_id != session['user_id']:
        return "Unauthorized"
        
    member = TeamMember.query.get_or_404(member_id)
    if action == 'accept':
        member.status = 'accepted'
    elif action == 'reject':
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

from flask import render_template, request, session, redirect, url_for, flash
from . import participant_bp
from app.extensions import db
from app.models import Hackathon, Team, TeamMember, User, HackathonStatus, ProblemStatement, TeamQR, TeamJoinRequest
from datetime import datetime
from flask import jsonify, current_app
from app.utils.qr_manager import generate_team_qrs
from functools import wraps
import uuid


def _parse_registered_skills(skills):
    """Parse comma-separated skills string into a list."""
    if not skills:
        return []
    return [s.strip() for s in skills.split(',') if s.strip()]

def participant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'participant':
            flash('Participant access only', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@participant_bp.route('/dashboard')
@participant_required
def dashboard():
    user_id = session.get('user_id')
    # Use join to get team details
    my_memberships = TeamMember.query.filter_by(user_id=user_id).all()

    pending_requests = TeamJoinRequest.query.filter_by(
        user_id=user_id,
        status='PENDING'
    ).order_by(TeamJoinRequest.created_at.desc()).all()
    
    # If the participant is already registered in any hackathon (via team membership),
    # don't show registration cards again.
    open_hackathons = []
    if not my_memberships:
        open_hackathons = Hackathon.query.filter_by(status=HackathonStatus.REGISTRATION_OPEN).all()
    
    return render_template('participant/dashboard.html', 
                           my_memberships=my_memberships, 
                           open_hackathons=open_hackathons,
                           pending_requests=pending_requests)

@participant_bp.route('/hackathon/<int:hackathon_id>/register', methods=['GET', 'POST'])
@participant_required
def register_hackathon(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)

    # Provide existing registered skills to the template so team-joining doesn't
    # force the user to re-enter them.
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None
    existing_skills = user.skills if user else ''
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = session['user_id']

        # A participant can only be registered in ONE hackathon at a time.
        # If they're already in any team, block registering again.
        existing_membership = TeamMember.query.join(Team).filter(TeamMember.user_id == user_id).first()
        if existing_membership:
            existing_team = existing_membership.team
            if existing_team and existing_team.hackathon_id == hackathon_id:
                flash("You are already registered for this hackathon.", 'warning')
            else:
                existing_name = existing_team.hackathon.name if existing_team and existing_team.hackathon else 'another hackathon'
                flash(f"You are already registered for {existing_name}. You can't register for a second hackathon.", 'error')
            return redirect(url_for('participant.dashboard'))
        
        if action == 'create_team':
            team_name = request.form.get('team_name')
            if not team_name or not team_name.strip():
                flash('Team name is required.', 'error')
                return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            team = Team(name=team_name, hackathon_id=hackathon.id, leader_id=user_id)
            try:
                db.session.add(team)
                db.session.commit()

                member = TeamMember(team_id=team.id, user_id=user_id)
                db.session.add(member)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Registration failed. Please try again.', 'error')
                return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            # Generate QRs
            try:
                generate_team_qrs(team.id)
            except Exception as e:
                print(f"QR Generation failed: {e}")
            
            flash("Team created successfully!", 'success')
            return redirect(url_for('participant.dashboard'))

        flash('Invalid action.', 'error')
        return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                
    return render_template('participant/hackathon_register.html', hackathon=hackathon, existing_skills=existing_skills)

@participant_bp.route('/team/<int:team_id>')
@participant_required
def view_team(team_id):
    team = Team.query.get_or_404(team_id)
    # Security: check membership
    is_member = TeamMember.query.filter_by(team_id=team.id, user_id=session['user_id']).first()
    if not is_member:
        flash("Access Denied", 'error')
        return redirect(url_for('participant.dashboard'))
    
    # Filter available problems: Only those not at capacity
    available_problems = []
    if team.hackathon.status == HackathonStatus.PROBLEM_SELECTION:
        all_problems = ProblemStatement.query.filter_by(hackathon_id=team.hackathon_id).all()
        available_problems = [p for p in all_problems if len(p.teams) < p.max_team_limit]
        
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

@participant_bp.route('/team/<int:team_id>/member/<int:member_id>/remove', methods=['POST'])
@participant_required
def remove_member(team_id, member_id):
    team = Team.query.get_or_404(team_id)
    if team.leader_id != session['user_id']:
        flash('Only the team leader can remove members.', 'error')
        return redirect(url_for('participant.view_team', team_id=team.id))

    # Ensure the membership row actually belongs to this team.
    member = TeamMember.query.filter_by(id=member_id, team_id=team.id).first_or_404()

    # Never allow removing the team leader.
    if member.user_id == team.leader_id:
        flash('You cannot remove the team leader.', 'error')
        return redirect(url_for('participant.view_team', team_id=team.id))

    user = User.query.get(member.user_id)
    db.session.delete(member)

    # Clean up any join requests for this team/user (pending/accepted/etc.)
    TeamJoinRequest.query.filter_by(team_id=team.id, user_id=member.user_id).delete(synchronize_session=False)

    # If the participant is now solo again, make them discoverable.
    # (Find Members list only shows `is_public == True`.)
    if user:
        remaining_memberships = TeamMember.query.filter_by(user_id=user.id).count()
        if remaining_memberships == 0:
            user.is_public = True
    db.session.commit()
    return redirect(url_for('participant.view_team', team_id=team.id))

@participant_bp.route('/team-requests/<int:request_id>/accept', methods=['POST'])
@participant_required
def accept_team_request(request_id):
    user_id = session.get('user_id')
    join_request = TeamJoinRequest.query.get_or_404(request_id)

    if join_request.user_id != user_id:
        flash('Unauthorized request action.', 'error')
        return redirect(url_for('participant.dashboard'))

    if join_request.status != 'PENDING':
        flash('This request is no longer pending.', 'warning')
        return redirect(url_for('participant.dashboard'))

    team = Team.query.get(join_request.team_id)
    if not team:
        flash('Team not found.', 'error')
        return redirect(url_for('participant.dashboard'))

    hackathon = team.hackathon
    if hackathon.status != HackathonStatus.REGISTRATION_OPEN:
        flash('Registration is not open for this hackathon.', 'error')
        return redirect(url_for('participant.dashboard'))

    if team.is_closed:
        flash('Team registration is closed.', 'error')
        return redirect(url_for('participant.dashboard'))

    current_members = TeamMember.query.filter_by(team_id=team.id).count()
    if current_members >= hackathon.max_team_size:
        flash('Team is full.', 'error')
        return redirect(url_for('participant.dashboard'))

    # The participant accepting this request is `join_request.user_id` (matches session user).
    # Policy: a participant can only be registered in ONE hackathon/team at a time.
    existing_membership = TeamMember.query.filter(TeamMember.user_id == join_request.user_id).first()
    if existing_membership:
        if existing_membership.team_id == team.id:
            # Already joined this team; finalize request status.
            try:
                join_request.status = 'ACCEPTED'
                join_request.responded_at = datetime.utcnow()
                db.session.commit()
                flash('You are already in this team.', 'info')
            except Exception:
                db.session.rollback()
                flash('Failed to update request status. Please try again.', 'error')
            return redirect(url_for('participant.dashboard'))

        flash('You are already registered in a team.', 'error')
        return redirect(url_for('participant.dashboard'))

    try:
        new_member = TeamMember(team_id=team.id, user_id=join_request.user_id)
        db.session.add(new_member)

        participant = User.query.get(join_request.user_id)
        if participant:
            participant.is_public = False

        join_request.status = 'ACCEPTED'
        join_request.responded_at = datetime.utcnow()

        db.session.commit()
        flash('Team request accepted. The member has joined your team.', 'success')
    except Exception:
        db.session.rollback()
        flash('Failed to accept the request. Please try again.', 'error')

    return redirect(url_for('participant.dashboard'))

@participant_bp.route('/team-requests/<int:request_id>/reject', methods=['POST'])
@participant_required
def reject_team_request(request_id):
    user_id = session.get('user_id')
    join_request = TeamJoinRequest.query.get_or_404(request_id)

    if join_request.user_id != user_id:
        flash('Unauthorized request action.', 'error')
        return redirect(url_for('participant.dashboard'))

    if join_request.status != 'PENDING':
        flash('This request is no longer pending.', 'warning')
        return redirect(url_for('participant.dashboard'))

    try:
        join_request.status = 'REJECTED'
        join_request.responded_at = datetime.utcnow()
        db.session.commit()
        flash('Team request rejected.', 'info')
    except Exception:
        db.session.rollback()
        flash('Failed to reject the request. Please try again.', 'error')

    return redirect(url_for('participant.dashboard'))

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
        flash('Only team leader can find members', 'error')
        return redirect(url_for('participant.view_team', team_id=team_id))
    
    return render_template('participant/team_find.html', hackathon=hackathon, team=team)

@participant_bp.route('/hackathon/<int:hackathon_id>/solo_register', methods=['POST'])
@participant_required
def solo_register(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)
    
    # A participant can only be registered in ONE hackathon at a time.
    existing_membership = TeamMember.query.join(Team).filter(TeamMember.user_id == user_id).first()
    if existing_membership:
        existing_team = existing_membership.team
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': "Already registered in a hackathon"}, 400

        existing_name = existing_team.hackathon.name if existing_team and existing_team.hackathon else 'another hackathon'
        flash(f"You are already registered for {existing_name}.", 'error')
        return redirect(url_for('participant.dashboard'))
    
    # Reuse skills captured at account registration.
    # Don't overwrite `user.skills` during team joining/visibility unless it was empty.
    submitted_skills = (request.form.get('skills') or '').strip()
    if (not (user.skills or '').strip()) and submitted_skills:
        user.skills = submitted_skills
    user.is_public = True
    
    db.session.commit()
    
    flash('Profile updated. You are now visible to team leaders.', 'success')
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


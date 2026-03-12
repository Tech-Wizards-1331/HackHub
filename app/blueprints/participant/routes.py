from flask import render_template, request, session, redirect, url_for, flash
from . import participant_bp
from app.extensions import db
from app.models import Hackathon, Team, TeamMember, User, HackathonStatus, ProblemStatement, TeamQR, TeamJoinRequest, TeamRosterMember, UserRole, TeamVisibility
from app.utils.hackathon_lifecycle import sync_hackathon_status
from datetime import datetime
from flask import jsonify, current_app
from app.utils.qr_manager import generate_team_qrs
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from functools import wraps
import uuid
import re


def _parse_registered_skills(skills):
    """Parse comma-separated skills string into a list."""
    if not skills:
        return []
    return [s.strip() for s in skills.split(',') if s.strip()]

def _find_date_conflict(user_id, hackathon):
    if not hackathon or not hackathon.start_date:
        return None

    target_date = hackathon.start_date.date()
    return (
        TeamMember.query
        .join(Team, TeamMember.team_id == Team.id)
        .join(Hackathon, Team.hackathon_id == Hackathon.id)
        .filter(
            TeamMember.user_id == user_id,
            func.date(Hackathon.start_date) == target_date
        )
        .first()
    )

def _auto_close_registration_if_due(hackathon):
    if not hackathon:
        return False

    sync_hackathon_status(hackathon, commit=True)
    return hackathon.status != HackathonStatus.REGISTRATION_OPEN

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
    my_memberships = (
        TeamMember.query
        .join(Team, TeamMember.team_id == Team.id)
        .join(Hackathon, Team.hackathon_id == Hackathon.id)
        .options(joinedload(TeamMember.team).joinedload(Team.hackathon))
        .filter(TeamMember.user_id == user_id)
        .order_by(Hackathon.start_date.desc(), Hackathon.name.asc(), Team.name.asc())
        .all()
    )

    pending_requests = TeamJoinRequest.query.filter_by(
        user_id=user_id,
        status='PENDING'
    ).order_by(TeamJoinRequest.created_at.desc()).all()
    
    # Allow multiple hackathon registrations (date conflicts handled on submit).
    registered_hackathon_ids = (
        db.session.query(Team.hackathon_id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user_id)
        .distinct()
    )
    open_hackathons = (
        Hackathon.query
        .filter_by(status=HackathonStatus.REGISTRATION_OPEN)
        .filter(~Hackathon.id.in_(registered_hackathon_ids))
        .all()
    )

    # Auto-close any open hackathons that are due (today or past).
    filtered_open = []
    for h in open_hackathons:
        if _auto_close_registration_if_due(h):
            continue
        filtered_open.append(h)
    open_hackathons = filtered_open
    
    return render_template('participant/dashboard.html', 
                           my_memberships=my_memberships, 
                           open_hackathons=open_hackathons,
                           pending_requests=pending_requests)

@participant_bp.route('/hackathon/<int:hackathon_id>/register', methods=['GET', 'POST'])
@participant_required
def register_hackathon(hackathon_id):
    hackathon = Hackathon.query.get_or_404(hackathon_id)

    if _auto_close_registration_if_due(hackathon):
        flash('Registration is closed for this hackathon.', 'error')
        return redirect(url_for('participant.dashboard'))

    # Provide existing registered skills to the template so team-joining doesn't
    # force the user to re-enter them.
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None
    existing_skills = user.skills if user else ''
    leader_profile = None
    if user:
        leader_profile = {
            'full_name': user.full_name or user.username,
            'email': user.email,
            'university_name': user.college or '',
            'experience_level': user.experience_level or '',
            'skills': user.skills or '',
        }
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = session['user_id']

        # Allow multiple hackathons, but block same-date conflicts.
        existing_same_hackathon = (
            TeamMember.query
            .join(Team)
            .filter(TeamMember.user_id == user_id, Team.hackathon_id == hackathon_id)
            .first()
        )
        if existing_same_hackathon:
            flash("You are already registered for this hackathon.", 'warning')
            return redirect(url_for('participant.dashboard'))

        conflict = _find_date_conflict(user_id, hackathon)
        if conflict and conflict.team and conflict.team.hackathon_id != hackathon_id:
            flash('You are already registered for another hackathon on this date.', 'error')
            return redirect(url_for('participant.dashboard'))
        
        if action == 'create_team':
            team_name = request.form.get('team_name')
            if not team_name or not team_name.strip():
                flash('Team name is required.', 'error')
                return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            # Team roster inputs (leader is always included; additional members are optional)
            members_full_name = request.form.getlist('members_full_name[]')
            members_email = request.form.getlist('members_email[]')
            members_university = request.form.getlist('members_university[]')
            members_experience = request.form.getlist('members_experience[]')
            members_skills = request.form.getlist('members_skills[]')

            # Basic email validation
            email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

            def _norm(s: str) -> str:
                return (s or '').strip()

            # Leader profile (from DB) is the authoritative first roster entry.
            leader_user = User.query.get(user_id)
            if not leader_user:
                flash('User session invalid. Please login again.', 'error')
                return redirect(url_for('auth.login'))

            # Normalize experience level (some older accounts may have different casing)
            exp_map = {'beginner': 'Beginner', 'intern': 'Intern', 'expert': 'Expert'}
            leader_exp_raw = _norm(leader_user.experience_level)
            leader_exp = exp_map.get(leader_exp_raw.lower(), leader_exp_raw)

            roster = [
                {
                    'full_name': _norm(leader_user.full_name) or _norm(leader_user.username),
                    'email': _norm(leader_user.email),
                    'university_name': _norm(leader_user.college),
                    'experience_level': leader_exp,
                    'skills': _norm(leader_user.skills),
                    'is_leader': True,
                }
            ]

            # Additional members submitted from the form
            if any([members_full_name, members_email, members_university, members_experience, members_skills]):
                n = max(len(members_full_name), len(members_email), len(members_university), len(members_experience), len(members_skills))
                for i in range(n):
                    fn = _norm(members_full_name[i] if i < len(members_full_name) else '')
                    em = _norm(members_email[i] if i < len(members_email) else '')
                    un = _norm(members_university[i] if i < len(members_university) else '')
                    ex = _norm(members_experience[i] if i < len(members_experience) else '')
                    sk = _norm(members_skills[i] if i < len(members_skills) else '')

                    # Skip completely empty rows (defensive)
                    if not any([fn, em, un, ex, sk]):
                        continue

                    roster.append({
                        'full_name': fn,
                        'email': em,
                        'university_name': un,
                        'experience_level': exp_map.get(ex.lower(), ex),
                        'skills': sk,
                        'is_leader': False,
                    })

            # Validate roster constraints: min 1 (leader) max hackathon limit
            if len(roster) < 1:
                flash('Add at least 1 team member.', 'error')
                return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
            max_allowed = hackathon.max_team_size or 5
            if len(roster) > max_allowed:
                flash(f'Maximum {max_allowed} team members allowed (including the leader).', 'error')
                return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            allowed_experience = {'Beginner', 'Intern', 'Expert'}
            seen_emails = set()
            for m in roster:
                if not m['full_name']:
                    flash('Full Name is required for each member.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                if not m['email'] or not email_re.match(m['email']):
                    flash('A valid Email Address is required for each member.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                if m['email'].lower() in seen_emails:
                    flash('Each team member email must be unique.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                seen_emails.add(m['email'].lower())
                if not m['university_name']:
                    flash('University Name is required for each member.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                if not m.get('is_leader') and m['experience_level'] not in allowed_experience:
                    flash('Experience Level must be Beginner / Intern / Expert.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))
                if not m['skills']:
                    flash('Skills are required for each member.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            # Resolve roster emails to existing users (if any) BEFORE writing anything.
            # We still store the roster snapshot for all entries.
            resolved_users_by_email = {}
            for m in roster:
                existing_user = (
                    User.query
                    .filter(func.lower(User.email) == m['email'].lower())
                    .first()
                )
                if existing_user:
                    resolved_users_by_email[m['email'].lower()] = existing_user

            # Validate resolved users: must be participants and must not conflict with this hackathon/date.
            for email_lower, existing_user in resolved_users_by_email.items():
                if existing_user.role != UserRole.PARTICIPANT:
                    flash(f'User with email {email_lower} is not a participant.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

                existing_same_hackathon_member = (
                    TeamMember.query
                    .join(Team)
                    .filter(TeamMember.user_id == existing_user.id, Team.hackathon_id == hackathon_id)
                    .first()
                )
                if existing_same_hackathon_member:
                    flash(f'{email_lower} is already registered for this hackathon.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

                conflict = _find_date_conflict(existing_user.id, hackathon)
                if conflict and conflict.team and conflict.team.hackathon_id != hackathon_id:
                    flash(f'{email_lower} is already registered for another hackathon on this date.', 'error')
                    return redirect(url_for('participant.register_hackathon', hackathon_id=hackathon_id))

            team = Team(name=team_name, hackathon_id=hackathon.id, leader_id=user_id)
            try:
                db.session.add(team)
                db.session.flush()  # Get team.id without committing transaction

                # Create TeamMember records (real memberships) for existing users.
                # Always include leader explicitly.
                added_user_ids = set()
                db.session.add(TeamMember(team_id=team.id, user_id=user_id))
                added_user_ids.add(user_id)

                for m in roster:
                    existing_user = resolved_users_by_email.get(m['email'].lower())
                    if not existing_user:
                        continue
                    if existing_user.id in added_user_ids:
                        continue

                    db.session.add(TeamMember(team_id=team.id, user_id=existing_user.id))
                    added_user_ids.add(existing_user.id)

                    if getattr(existing_user, 'is_public', None):
                        existing_user.is_public = False
                
                # Persist the submitted roster snapshot (leader + optional additional members)
                # This stores registration metadata for record-keeping
                for m in roster:
                    db.session.add(TeamRosterMember(
                        team_id=team.id,
                        hackathon_id=hackathon.id,
                        full_name=m['full_name'],
                        email=m['email'],
                        university_name=m['university_name'],
                        experience_level=m['experience_level'],
                        skills=m['skills'],
                        is_leader=bool(m.get('is_leader')),
                    ))
                
                # Commit all changes in single transaction (atomic)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Team registration error: {e}")
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
                
    return render_template(
        'participant/hackathon_register.html',
        hackathon=hackathon,
        existing_skills=existing_skills,
        leader_profile=leader_profile,
    )

@participant_bp.route('/team/<int:team_id>')
@participant_required
def view_team(team_id):
    team = Team.query.get_or_404(team_id)
    # Security: check membership
    is_member = TeamMember.query.filter_by(team_id=team.id, user_id=session['user_id']).first()
    if not is_member:
        flash("Access Denied", 'error')
        return redirect(url_for('participant.dashboard'))

    # Load roster snapshot (leader + added members from registration)
    roster_rows = (
        TeamRosterMember.query
        .filter_by(team_id=team.id, hackathon_id=team.hackathon_id)
        .order_by(TeamRosterMember.is_leader.desc(), TeamRosterMember.full_name.asc())
        .all()
    )

    members_by_email = {}
    members_by_user_id = {}
    for tm in team.members:
        if tm.user:
            members_by_user_id[tm.user_id] = tm
            if tm.user.email:
                members_by_email[tm.user.email.lower()] = tm

    roster_view = []
    linked_user_ids = set()
    for r in roster_rows:
        linked = members_by_email.get((r.email or '').lower())
        if linked:
            linked_user_ids.add(linked.user_id)
        roster_view.append({
            'full_name': r.full_name,
            'email': r.email,
            'is_leader': bool(r.is_leader),
            'linked_team_member_id': linked.id if linked else None,
            'linked_user_id': linked.user_id if linked else None,
            'linked_username': (linked.user.username if linked and linked.user else None),
            'linked_display_name': (linked.user.full_name if linked and linked.user else None),
        })

    # Include members added after registration, such as accepted join requests.
    for tm in team.members:
        if not tm.user or tm.user_id in linked_user_ids:
            continue
        roster_view.append({
            'full_name': tm.user.full_name or tm.user.username,
            'email': tm.user.email,
            'is_leader': tm.user_id == team.leader_id,
            'linked_team_member_id': tm.id,
            'linked_user_id': tm.user_id,
            'linked_username': tm.user.username,
            'linked_display_name': tm.user.full_name,
        })

    roster_view.sort(
        key=lambda row: (
            0 if row['is_leader'] else 1,
            (row['linked_display_name'] or row['full_name'] or row['linked_username'] or '').lower(),
        )
    )
    
    # Filter available problems: Only those not at capacity
    available_problems = []
    if team.hackathon.status == HackathonStatus.PROBLEM_SELECTION:
        all_problems = ProblemStatement.query.filter_by(hackathon_id=team.hackathon_id).all()
        available_problems = [p for p in all_problems if len(p.teams) < p.max_team_limit]
        
    return render_template('participant/team_view.html', team=team, available_problems=available_problems, roster_view=roster_view)

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
    if _auto_close_registration_if_due(hackathon):
        flash('Registration is closed for this hackathon.', 'error')
        return redirect(url_for('participant.dashboard'))
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
    existing_membership = (
        TeamMember.query
        .join(Team)
        .filter(
            TeamMember.user_id == join_request.user_id,
            Team.hackathon_id == hackathon.id,
        )
        .first()
    )
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

        flash('You are already in another team for this hackathon.', 'error')
        return redirect(url_for('participant.dashboard'))

    # Block same-date conflicts with other hackathons.
    conflict = _find_date_conflict(join_request.user_id, hackathon)
    if conflict and conflict.team and conflict.team.hackathon_id != hackathon.id:
        flash('You are already registered for another hackathon on this date.', 'error')
        return redirect(url_for('participant.dashboard'))

    try:
        new_member = TeamMember(team_id=team.id, user_id=join_request.user_id)
        db.session.add(new_member)

        participant = User.query.get(join_request.user_id)
        if participant:
            participant.is_public = False

        TeamVisibility.query.filter_by(
            hackathon_id=hackathon.id,
            user_id=join_request.user_id,
            is_active=True,
        ).update({'is_active': False})

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

    if _auto_close_registration_if_due(hackathon):
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': 'Registration is closed for this hackathon.'}, 400
        flash('Registration is closed for this hackathon.', 'error')
        return redirect(url_for('participant.dashboard'))
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)
    
    # Allow multiple hackathons, but block same-date conflicts.
    existing_same_hackathon = (
        TeamMember.query
        .join(Team)
        .filter(TeamMember.user_id == user_id, Team.hackathon_id == hackathon_id)
        .first()
    )
    if existing_same_hackathon:
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': "Already registered for this hackathon"}, 400
        flash("You are already registered for this hackathon.", 'warning')
        return redirect(url_for('participant.dashboard'))

    conflict = _find_date_conflict(user_id, hackathon)
    if conflict and conflict.team and conflict.team.hackathon_id != hackathon_id:
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': "You are already registered for another hackathon on this date."}, 400
        flash('You are already registered for another hackathon on this date.', 'error')
        return redirect(url_for('participant.dashboard'))

    existing_visibility = TeamVisibility.query.filter_by(
        hackathon_id=hackathon_id,
        user_id=user_id,
    ).first()
    if existing_visibility and existing_visibility.is_active:
        message = 'You are now visible to the team leaders. Please wait for their invitation.'
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'message': message}, 200
        flash(message, 'info')
        return redirect(url_for('participant.dashboard'))
    
    # Reuse skills captured at account registration.
    # Don't overwrite `user.skills` during team joining/visibility unless it was empty.
    submitted_skills = (request.form.get('skills') or '').strip()
    if (not (user.skills or '').strip()) and submitted_skills:
        user.skills = submitted_skills

    # Mark user visible and create/activate visibility entry for this hackathon.
    user.is_public = True
    if existing_visibility:
        existing_visibility.is_active = True
    else:
        db.session.add(TeamVisibility(hackathon_id=hackathon_id, user_id=user_id, is_active=True))

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


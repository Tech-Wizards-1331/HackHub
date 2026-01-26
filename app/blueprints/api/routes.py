from flask import jsonify, request, session
from . import api_bp
from app.extensions import db
from app.models import User, Team, TeamMember, Hackathon, HackathonStatus, UserRole
from sqlalchemy import and_

@api_bp.route('/status')
def status():
    return jsonify({'status': 'ok'})

@api_bp.route('/hackathon/<int:hackathon_id>/solo_participants', methods=['GET'])
def get_solo_participants(hackathon_id):
    """
    Get solo participants (team_id = NULL) for a hackathon
    Filter by skills if provided
    """
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    
    if hackathon.status != HackathonStatus.REGISTRATION_OPEN:
        return jsonify({'error': 'Registration not open'}), 400
    
    skills_filter = request.args.get('skills', '').strip()
    
    # Get users who are participants AND not in any team for this hackathon AND is_public = TRUE
    solo_query = db.session.query(User).filter(
        User.role == UserRole.PARTICIPANT,
        User.is_public == True,
        ~User.id.in_(
            db.session.query(TeamMember.user_id).join(Team).filter(
                Team.hackathon_id == hackathon_id
            )
        )
    )
    
    if skills_filter:
        requested_skills = [s.strip().lower() for s in skills_filter.split(',')]
        for skill in requested_skills:
            solo_query = solo_query.filter(User.skills.ilike(f'%{skill}%'))
    
    solo_participants = solo_query.all()
    
    result = []
    for user in solo_participants:
        result.append({
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'skills': user.skills,
            'experience_level': user.experience_level,
            'college': user.college
        })
    
    return jsonify({'participants': result}), 200

@api_bp.route('/hackathon/<int:hackathon_id>/team/<int:team_id>/add_member', methods=['POST'])
def add_member_to_team(hackathon_id, team_id):
    """
    Team leader directly adds a solo participant to their team
    NO approval needed
    """
    if session.get('role') != 'participant':
        return jsonify({'error': 'Unauthorized'}), 403
    
    user_id = session.get('user_id')
    data = request.get_json()
    participant_id = data.get('participant_id')
    
    if not participant_id:
        return jsonify({'error': 'participant_id required'}), 400
    
    hackathon = Hackathon.query.get_or_404(hackathon_id)
    team = Team.query.get_or_404(team_id)
    participant = User.query.get_or_404(participant_id)
    
    # Validation 1: Must be team leader
    if team.leader_id != user_id:
        return jsonify({'error': 'Only team leader can add members'}), 403
    
    # Validation 2: Team belongs to hackathon
    if team.hackathon_id != hackathon_id:
        return jsonify({'error': 'Team does not belong to this hackathon'}), 400
    
    # Validation 3: Hackathon must be in REGISTRATION_OPEN
    if hackathon.status != HackathonStatus.REGISTRATION_OPEN:
        return jsonify({'error': 'Registration not open'}), 400
    
    # Validation 4: Registration must not be locked
    if team.is_closed:
        return jsonify({'error': 'Team registration is closed'}), 400
    
    # Validation 5: Team must not be full
    current_members = TeamMember.query.filter_by(team_id=team_id).count()
    if current_members >= hackathon.max_team_size:
        return jsonify({'error': 'Team is full'}), 400
    
    # Validation 6: Participant must be a participant
    if participant.role != UserRole.PARTICIPANT:
        return jsonify({'error': 'User is not a participant'}), 400
    
    # Validation 7: Participant must still be solo (not in any team for this hackathon)
    existing_membership = TeamMember.query.join(Team).filter(
        and_(
            Team.hackathon_id == hackathon_id,
            TeamMember.user_id == participant_id
        )
    ).first()
    
    if existing_membership:
        return jsonify({'error': 'Participant already in a team'}), 400
    
    # DIRECT ADD (NO APPROVAL)
    try:
        new_member = TeamMember(
            team_id=team_id,
            user_id=participant_id
        )
        db.session.add(new_member)
        
        # Auto-hide: Set is_public to FALSE
        participant.is_public = False
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Participant added to team',
            'member': {
                'id': new_member.id,
                'user_id': participant_id,
                'username': participant.username,
                'full_name': participant.full_name
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to add member', 'details': str(e)}), 500

from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import participant_bp
from app.extensions import db
from app.models import Hackathon, Team, TeamMember, User, HackathonStatus, ProblemStatement
from functools import wraps
import uuid

def participant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'participant':
            flash('Participant access only', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@participant_bp.route('/hackathon/<int:hackathon_id>/select_problem', methods=['POST'])
@participant_required
def select_problem(hackathon_id):
    user_id = session['user_id']
    problem_id = request.form.get('problem_id')

    if not problem_id:
        flash("No problem selected", "error")
        return redirect(url_for('participant.dashboard'))

    # Start Transaction
    try:
        # 1. Get Hackathon & Verify Status (Phase check)
        hackathon = Hackathon.query.get_or_404(hackathon_id)
        if hackathon.status != HackathonStatus.PROBLEM_SELECTION:
            flash("Problem selection is not open", "error")
            return redirect(url_for('participant.dashboard'))

        # 2. Get User's Team & Verify Leadership
        team = Team.query.filter_by(
            hackathon_id=hackathon_id, 
            leader_id=user_id
        ).first()

        if not team:
            flash("Only Team Leaders can select problem statements", "error")
            return redirect(url_for('participant.dashboard'))
        
        # 3. Check if already selected
        if team.problem_statement_id:
            flash("Team has already selected a problem statement", "error")
            return redirect(url_for('participant.dashboard'))

        # 4. Lock Problem Statement Row for Update (ATOMICTY)
        problem = ProblemStatement.query.with_for_update().get(problem_id)
        
        if not problem or problem.hackathon_id != hackathon_id:
            flash("Invalid problem statement", "error")
            db.session.rollback()
            return redirect(url_for('participant.dashboard'))

        # 5. Check Capacity
        current_count = Team.query.filter_by(problem_statement_id=problem_id).count() 
        # Note: We can trust count here because we hold a lock on the *problem* row? 
        # Actually, Locking the problem row doesn't prevent inserting into Team table with that ID unless we have foreign key locking or explicit logic.
        # But since all selection goes through this critical section where we lock the *problem*, and we check count, 
        # concurrent transactions will wait for the lock on 'problem' before reading/writing.
        # Ideally, we should also lock the teams that have this problem, but locking the problem itself acts as a semaphore if everyone follows protocol.
        
        if current_count >= problem.max_team_limit:
            flash("Problem statement is full", "error")
            db.session.rollback()
            return redirect(url_for('participant.dashboard'))

        # 6. Assign
        team.problem_statement_id = problem.id
        db.session.commit()
        
        flash(f"Successfully selected problem: {problem.title}", "success")
        return redirect(url_for('participant.dashboard'))

    except Exception as e:
        db.session.rollback()
        flash(f"Selection failed: {str(e)}", "error")
        return redirect(url_for('participant.dashboard'))

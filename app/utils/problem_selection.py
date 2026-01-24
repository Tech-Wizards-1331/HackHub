from app.extensions import db
from app.models import Hackathon, Team, ProblemStatement, HackathonStatus
import random

def auto_assign_problems(hackathon_id):
    """
    Auto-assigns problem statements to teams that haven't selected one.
    To be called 1 hour after PROBLEM_SELECTION phase starts.
    """
    try:
        hackathon = Hackathon.query.get(hackathon_id)
        if not hackathon or hackathon.status != HackathonStatus.PROBLEM_SELECTION:
            return {"status": "error", "message": "Invalid phase"}

        # Get unassigned teams (and lock them to prevent race conditions during this batch process)
        # However, locking many rows might be heavy. We will process one by one or in batch.
        # Let's get list first.
        unassigned_teams = Team.query.filter_by(hackathon_id=hackathon_id, problem_statement_id=None).all()
        
        if not unassigned_teams:
            return {"status": "success", "message": "No unassigned teams"}
            
        # Get all problems
        problems = ProblemStatement.query.filter_by(hackathon_id=hackathon_id).all()
        if not problems:
            return {"status": "error", "message": "No problems available"}

        assigned_count = 0
        
        for team in unassigned_teams:
            # Refresh context per team to be safe or do it in one big loop?
            # One big transaction is risky if list is huge, but safer for consistency.
            # We will use nested savepoints or just simple logic for now.
            
            # Find available problem
            # Shuffle to ensure randomness distribution
            random.shuffle(problems)
            
            selected_problem = None
            for p in problems:
                # Check real-time count
                curr_count = Team.query.filter_by(problem_statement_id=p.id).count()
                if curr_count < p.max_team_limit:
                    selected_problem = p
                    break
            
            if selected_problem:
                team.problem_statement_id = selected_problem.id
                assigned_count += 1
            else:
                # Failure Case: No spots left in any problem
                # Log this or leave as None (as per req "Store this state in DB" -> None is the state)
                pass

        db.session.commit()
        return {"status": "success", "assigned": assigned_count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}

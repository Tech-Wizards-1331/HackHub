from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import faculty_bp
from app.extensions import db
from app.models import User, Team, TeamMember, Evaluation, Hackathon, HackathonStatus, FacultyAssignment, TeamQR, MealScan
from functools import wraps
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import re
from urllib.parse import urlparse, parse_qs
from sqlalchemy import func

def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'faculty':
            flash('Faculty access only')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


MEAL_TYPES = {'breakfast', 'lunch', 'dinner'}


def _normalize_meal_type(raw_value):
    if not raw_value:
        return None
    normalized = str(raw_value).strip().lower()
    return normalized if normalized in MEAL_TYPES else None


UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


def _extract_qr_tokens(raw_value):
    if not raw_value:
        return []

    raw = str(raw_value).strip()
    if not raw:
        return []

    candidates = []

    def add_candidate(value):
        v = (value or '').strip()
        if v and v not in candidates:
            candidates.append(v)

    add_candidate(raw)

    # Legacy payload format: "MEAL|meal_type|token|name"
    if raw.startswith('MEAL|'):
        parts = raw.split('|')
        if len(parts) >= 3:
            add_candidate(parts[2])

    # URL payload support: ?token=... or ?qr_token=...
    if '://' in raw:
        try:
            parsed = urlparse(raw)
            params = parse_qs(parsed.query or '')
            for key in ('token', 'qr_token'):
                for value in params.get(key, []):
                    add_candidate(value)
        except Exception:
            pass

    # Scanner may include extra prefixes/suffixes; pull UUID-like token if present.
    for match in UUID_RE.findall(raw):
        add_candidate(match)

    return candidates


def _extract_user_hint(raw_value):
    if not raw_value:
        return None
    raw = str(raw_value).strip()
    if not raw:
        return None

    if raw.startswith('MEAL|'):
        parts = raw.split('|')
        if len(parts) >= 4:
            hint = parts[3].strip()
            return hint or None

    return None


def _supports_row_locking():
    dialect = (db.session.bind.dialect.name if db.session.bind else '').lower()
    return dialect in ('postgresql', 'mysql')


def _lock_team_scope(team_id, hackathon_id, meal_type):
    if not _supports_row_locking():
        return

    db.session.execute(
        text('SELECT id FROM teams WHERE id = :team_id AND hackathon_id = :hackathon_id FOR UPDATE'),
        {'team_id': team_id, 'hackathon_id': hackathon_id}
    )
    db.session.execute(
        text('SELECT id FROM team_members WHERE team_id = :team_id FOR UPDATE'),
        {'team_id': team_id}
    )
    db.session.execute(
        text('''
            SELECT id
            FROM meal_scans
            WHERE team_id = :team_id
              AND hackathon_id = :hackathon_id
              AND meal_type = :meal_type
            FOR UPDATE
        '''),
        {'team_id': team_id, 'hackathon_id': hackathon_id, 'meal_type': meal_type}
    )


def _get_team_meal_stats(team_id, hackathon_id, meal_type):
    total_members = db.session.query(TeamMember).filter_by(team_id=team_id).count()
    already_taken = db.session.query(MealScan).filter_by(
        team_id=team_id,
        hackathon_id=hackathon_id,
        meal_type=meal_type
    ).count()
    remaining = max(total_members - already_taken, 0)
    return total_members, already_taken, remaining


def _allocate_meals_atomic(team_id, hackathon_id, meal_type, requested_count, scanned_by):
    team = Team.query.filter_by(id=team_id, hackathon_id=hackathon_id).first()
    if not team:
        return {'ok': False, 'status': 404, 'message': 'Invalid team for this hackathon.'}

    if requested_count <= 0:
        return {'ok': False, 'status': 400, 'message': 'requested_count must be at least 1.'}

    try:
        with db.session.begin_nested():
            _lock_team_scope(team_id, hackathon_id, meal_type)

            total_members, already_taken, remaining = _get_team_meal_stats(team_id, hackathon_id, meal_type)

            if total_members == 0:
                return {'ok': False, 'status': 400, 'message': 'Team has no members.'}

            if remaining == 0:
                return {'ok': False, 'status': 409, 'message': 'All members already took this meal.'}

            if requested_count > remaining:
                return {
                    'ok': False,
                    'status': 409,
                    'message': f'Request exceeds remaining limit. Remaining: {remaining}.',
                    'stats': {
                        'total_members': total_members,
                        'already_taken': already_taken,
                        'remaining': remaining,
                    }
                }

            params = {
                'hackathon_id': hackathon_id,
                'team_id': team_id,
                'meal_type': meal_type,
                'requested_count': requested_count,
                'scanned_by': scanned_by,
            }

            dialect_name = db.session.get_bind().dialect.name
            if dialect_name == 'sqlite':
                insert_sql = text('''
                    WITH eligible AS (
                        SELECT tm.user_id AS participant_id
                        FROM team_members tm
                        LEFT JOIN meal_scans ms
                          ON ms.hackathon_id = :hackathon_id
                         AND ms.team_id = :team_id
                         AND ms.meal_type = :meal_type
                         AND ms.participant_id = tm.user_id
                        WHERE tm.team_id = :team_id
                          AND ms.id IS NULL
                        ORDER BY tm.id
                        LIMIT :requested_count
                    )
                    INSERT OR IGNORE INTO meal_scans (hackathon_id, participant_id, team_id, meal_type, scanned_by, scanned_at)
                    SELECT :hackathon_id, participant_id, :team_id, :meal_type, :scanned_by, CURRENT_TIMESTAMP
                    FROM eligible
                ''')
                result = db.session.execute(insert_sql, params)
                inserted_count = int(result.rowcount or 0)
            else:
                insert_sql = text('''
                    WITH eligible AS (
                        SELECT tm.user_id AS participant_id
                        FROM team_members tm
                        LEFT JOIN meal_scans ms
                          ON ms.hackathon_id = :hackathon_id
                         AND ms.team_id = :team_id
                         AND ms.meal_type = :meal_type
                         AND ms.participant_id = tm.user_id
                        WHERE tm.team_id = :team_id
                          AND ms.id IS NULL
                        ORDER BY tm.id
                        LIMIT :requested_count
                    )
                    INSERT INTO meal_scans (hackathon_id, participant_id, team_id, meal_type, scanned_by, scanned_at)
                    SELECT :hackathon_id, participant_id, :team_id, :meal_type, :scanned_by, CURRENT_TIMESTAMP
                    FROM eligible
                    ON CONFLICT (hackathon_id, participant_id, meal_type) DO NOTHING
                    RETURNING participant_id
                ''')
                inserted_rows = db.session.execute(insert_sql, params).fetchall()
                inserted_count = len(inserted_rows)

            if inserted_count != requested_count:
                raise IntegrityError(
                    f'Expected to insert {requested_count}, inserted {inserted_count}.',
                    None,
                    None
                )

        db.session.commit()

        total_members, already_taken, remaining = _get_team_meal_stats(team_id, hackathon_id, meal_type)
        return {
            'ok': True,
            'status': 200,
            'message': f'Meal recorded for {inserted_count} member(s).',
            'stats': {
                'total_members': total_members,
                'already_taken': already_taken,
                'remaining': remaining,
            }
        }
    except IntegrityError:
        db.session.rollback()
        total_members, already_taken, remaining = _get_team_meal_stats(team_id, hackathon_id, meal_type)
        return {
            'ok': False,
            'status': 409,
            'message': 'Concurrent update detected. Please retry with updated remaining count.',
            'stats': {
                'total_members': total_members,
                'already_taken': already_taken,
                'remaining': remaining,
            }
        }
    except Exception as e:
        db.session.rollback()
        return {'ok': False, 'status': 500, 'message': f'Failed to record meal scan: {e}'}

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
        if request.is_json:
            # AJAX/JSON request
            raw_qr_value = request.get_json().get('qr_token')
            qr_token_candidates = _extract_qr_tokens(raw_qr_value)
            user_hint = _extract_user_hint(raw_qr_value)
            
            if not qr_token_candidates:
                return jsonify({'status': 'error', 'message': 'Token missing'}), 400
            
            try:
                # 1) Try team-level QR token
                qr_record = None
                for token in qr_token_candidates:
                    qr_record = TeamQR.query.filter_by(qr_token=token).first()
                    if qr_record:
                        break
                team = None
                qr_type = 'ACCESS'
                if qr_record:
                    team = Team.query.get(qr_record.team_id)
                    qr_type = qr_record.qr_type

                # 2) Fallback: participant personal QR token -> resolve participant team
                if not team:
                    user = None
                    for token in qr_token_candidates:
                        user = User.query.filter_by(qr_token=token).first()
                        if user:
                            break
                    if not user and user_hint:
                        normalized_hint = user_hint.strip().lower()
                        user = User.query.filter(
                            (func.lower(User.full_name) == normalized_hint) |
                            (func.lower(User.username) == normalized_hint)
                        ).first()
                    if user:
                        team_member = TeamMember.query.filter_by(user_id=user.id).join(Team).first()
                        if team_member:
                            team = team_member.team
                            qr_type = 'ACCESS'

                if not team:
                    return jsonify({'status': 'error', 'message': 'Invalid QR Token'}), 404

                response_data = {
                    'team_name': team.name,
                    'hackathon': team.hackathon.name,
                    'qr_type': qr_type,
                    'team_id': team.id,
                    'hackathon_id': team.hackathon_id
                }

                enabled_meals = []
                if team.hackathon.enable_breakfast:
                    enabled_meals.append('breakfast')
                if team.hackathon.enable_lunch:
                    enabled_meals.append('lunch')
                if team.hackathon.enable_dinner:
                    enabled_meals.append('dinner')
                if not enabled_meals:
                    # Simple fallback so modal flow always works even if meal flags are not configured.
                    enabled_meals = ['lunch']
                
                # Process by QR Type
                if qr_type == 'ACCESS':
                    response_data.update({
                        'enabled_meals': enabled_meals,
                        'meal_type': enabled_meals[0],
                    })
                    return jsonify({
                        'status': 'success',
                        'action': 'meal_allocation_required',
                        'message': 'Team QR verified. Select meal type and enter members taking meal.',
                        'data': response_data
                    }), 200
                
                elif qr_type in ['BREAKFAST', 'LUNCH', 'DINNER']:
                    meal_type = _normalize_meal_type(qr_type)
                    if not meal_type:
                        return jsonify({'status': 'error', 'message': 'Unsupported meal type'}), 400

                    total_members, already_taken, remaining = _get_team_meal_stats(
                        team.id,
                        team.hackathon_id,
                        meal_type
                    )

                    response_data.update({
                        'meal_type': meal_type,
                        'enabled_meals': enabled_meals or [meal_type],
                        'total_members': total_members,
                        'already_taken': already_taken,
                        'remaining': remaining,
                    })

                    if remaining == 0:
                        return jsonify({
                            'status': 'error',
                            'message': 'All members already took this meal.',
                            'data': response_data
                        }), 409

                    return jsonify({
                        'status': 'success',
                        'action': 'meal_allocation_required',
                        'message': f'{qr_type} QR verified. Enter members taking meal.',
                        'data': response_data
                    }), 200
                
                return jsonify({'status': 'error', 'message': 'Unknown QR Type'}), 400
                
            except Exception as e:
                db.session.rollback()
                return jsonify({'status': 'error', 'message': str(e)}), 500
        else:
            # Form POST - redirect back
            return redirect(url_for('faculty.scan_qr'))
            
    return render_template('faculty/scan.html')


@faculty_bp.route('/scan_qr/remaining', methods=['GET'])
@faculty_required
def meal_scan_remaining():
    team_id = request.args.get('team_id', type=int)
    hackathon_id = request.args.get('hackathon_id', type=int)
    meal_type = _normalize_meal_type(request.args.get('meal_type'))

    if not team_id or not hackathon_id or not meal_type:
        return jsonify({'status': 'error', 'message': 'team_id, hackathon_id and meal_type are required.'}), 400

    team = Team.query.filter_by(id=team_id, hackathon_id=hackathon_id).first()
    if not team:
        return jsonify({'status': 'error', 'message': 'Invalid team for this hackathon.'}), 404

    total_members, already_taken, remaining = _get_team_meal_stats(team_id, hackathon_id, meal_type)
    return jsonify({
        'status': 'success',
        'data': {
            'team_id': team_id,
            'hackathon_id': hackathon_id,
            'meal_type': meal_type,
            'total_members': total_members,
            'already_taken': already_taken,
            'remaining': remaining,
        }
    }), 200


@faculty_bp.route('/scan_qr/submit', methods=['POST'])
@faculty_required
def submit_team_meal_scan():
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'JSON body required.'}), 400

    payload = request.get_json(silent=True) or {}
    team_id = payload.get('team_id')
    hackathon_id = payload.get('hackathon_id')
    meal_type = _normalize_meal_type(payload.get('meal_type'))
    requested_count = payload.get('requested_count')

    try:
        team_id = int(team_id)
        hackathon_id = int(hackathon_id)
        requested_count = int(requested_count)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'team_id, hackathon_id and requested_count must be integers.'}), 400

    if not meal_type:
        return jsonify({'status': 'error', 'message': 'Invalid meal_type.'}), 400

    result = _allocate_meals_atomic(
        team_id=team_id,
        hackathon_id=hackathon_id,
        meal_type=meal_type,
        requested_count=requested_count,
        scanned_by=session['user_id']
    )

    status_text = 'success' if result['ok'] else 'error'
    return jsonify({
        'status': status_text,
        'message': result['message'],
        'data': result.get('stats', {})
    }), result['status']

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
                stage_id=1,
                score=float(total_score),
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

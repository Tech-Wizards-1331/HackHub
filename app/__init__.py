from flask import Flask
from config import Config
from .extensions import db, migrate, sess
from sqlalchemy import text

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Configure Server-side sessions
    app.config['SESSION_TYPE'] = 'filesystem'
    
    db.init_app(app)
    migrate.init_app(app, db)
    sess.init_app(app)

    # Ensure model metadata is registered before any create_all()/migrations.
    from . import models  # noqa: F401
    
    from .blueprints.auth import auth_bp
    from .blueprints.admin import admin_bp
    from .blueprints.faculty import faculty_bp
    from .blueprints.participant import participant_bp
    from .blueprints.api import api_bp
    from .blueprints.qr import qr_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(faculty_bp, url_prefix='/faculty')
    app.register_blueprint(participant_bp, url_prefix='/participant')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(qr_bp)
    
    @app.route('/')
    def index():
        from flask import render_template
        return render_template('public/index.html')
        
    with app.app_context():
        # Lightweight SQLite schema migration for existing local DBs.
        # `create_all()` will not add new columns to existing tables.
        try:
            uri = app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
            if uri.startswith('sqlite:'):
                # Local/dev convenience: ensure base tables exist for SQLite.
                # Postgres schema should be managed via Alembic (Flask-Migrate) instead.
                db.create_all()

                # Ensure hackathons meal columns exist (older DBs won't have them).
                hack_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(hackathons)')).all()]
                hack_desired = {
                    'enable_breakfast': 'INTEGER DEFAULT 0',
                    'enable_lunch': 'INTEGER DEFAULT 0',
                    'enable_dinner': 'INTEGER DEFAULT 0',
                    'breakfast_time': 'VARCHAR(5)',
                    'lunch_time': 'VARCHAR(5)',
                    'dinner_time': 'VARCHAR(5)',
                    'end_date': 'DATETIME',
                }
                hack_missing = [(name, col_type) for name, col_type in hack_desired.items() if name not in hack_cols]
                for name, col_type in hack_missing:
                    db.session.execute(text(f'ALTER TABLE hackathons ADD COLUMN {name} {col_type}'))
                if hack_missing:
                    db.session.commit()

                # Ensure users.created_at exists (needed for registration trends).
                user_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(users)')).all()]
                if 'created_at' not in user_cols:
                    db.session.execute(text('ALTER TABLE users ADD COLUMN created_at DATETIME'))
                    db.session.execute(text("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
                    db.session.commit()

                cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(faculty_assignments)')).all()]
                if 'assigned_at' not in cols:
                    db.session.execute(text('ALTER TABLE faculty_assignments ADD COLUMN assigned_at DATETIME'))
                    db.session.commit()

                # Legacy schema compatibility: older DBs may have an `evaluations` table
                # without the newer columns used by the app.
                eval_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(evaluations)')).all()]
                missing = []
                desired = {
                    'hackathon_id': 'INTEGER',
                    'innovation_score': 'INTEGER',
                    'technical_score': 'INTEGER',
                    'uiux_score': 'INTEGER',
                    'practicality_score': 'INTEGER',
                    'presentation_score': 'INTEGER',
                    'total_score': 'FLOAT',
                    'created_at': 'DATETIME',
                }
                for name, col_type in desired.items():
                    if name not in eval_cols:
                        missing.append((name, col_type))

                for name, col_type in missing:
                    db.session.execute(text(f'ALTER TABLE evaluations ADD COLUMN {name} {col_type}'))

                # Backfill: derive hackathon_id from teams where possible.
                if 'hackathon_id' in [n for n, _ in missing] or 'hackathon_id' in eval_cols:
                    try:
                        team_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(teams)')).all()]
                        if 'hackathon_id' in team_cols and 'team_id' in eval_cols:
                            db.session.execute(text('''
                                UPDATE evaluations
                                SET hackathon_id = (
                                    SELECT teams.hackathon_id FROM teams WHERE teams.id = evaluations.team_id
                                )
                                WHERE hackathon_id IS NULL
                            '''))
                    except Exception:
                        pass

                # Backfill: if legacy `score` exists, copy into `total_score` for results display.
                if 'score' in eval_cols:
                    try:
                        db.session.execute(text('UPDATE evaluations SET total_score = score WHERE total_score IS NULL'))
                    except Exception:
                        pass

                if missing:
                    db.session.commit()
        except Exception:
            # If migration fails, don't prevent app from starting; route handlers will surface issues.
            db.session.rollback()
        
    return app

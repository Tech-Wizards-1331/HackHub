from flask import Flask
from config import Config
from .extensions import db, sess

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Configure Server-side sessions
    app.config['SESSION_TYPE'] = 'filesystem'
    
    db.init_app(app)
    sess.init_app(app)
    
    from .blueprints.auth import auth_bp
    from .blueprints.admin import admin_bp
    from .blueprints.faculty import faculty_bp
    from .blueprints.participant import participant_bp
    from .blueprints.api import api_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(faculty_bp, url_prefix='/faculty')
    app.register_blueprint(participant_bp, url_prefix='/participant')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    @app.route('/')
    def index():
        from flask import render_template
        return render_template('public/index.html')
        
    with app.app_context():
        db.create_all()
        
    return app

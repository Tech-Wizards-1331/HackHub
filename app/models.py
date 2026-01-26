from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db
import enum

class UserRole(enum.Enum):
    ADMIN = 'admin'
    FACULTY = 'faculty'
    PARTICIPANT = 'participant'

class HackathonStatus(enum.Enum):
    DRAFT = 'DRAFT'
    REGISTRATION_OPEN = 'REGISTRATION_OPEN'
    REGISTRATION_CLOSED = 'REGISTRATION_CLOSED'
    PROBLEM_SELECTION = 'PROBLEM_SELECTION'
    ONGOING = 'ONGOING'
    EVALUATION = 'EVALUATION'
    RESULT_PUBLISHED = 'RESULT_PUBLISHED'
    ARCHIVED = 'ARCHIVED'

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False)
    
    # Profile fields
    full_name = db.Column(db.String(100))
    skills = db.Column(db.Text) # Comma separated or JSON
    experience_level = db.Column(db.String(50))
    college = db.Column(db.String(100))
    is_public = db.Column(db.Boolean, default=False)
    
    # QR Code
    registration_qr = db.Column(db.String(200)) # Path or string data
    is_present = db.Column(db.Boolean, default=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Hackathon(db.Model):
    __tablename__ = 'hackathons'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    venue = db.Column(db.String(150))
    status = db.Column(db.Enum(HackathonStatus), default=HackathonStatus.DRAFT)
    
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    
    max_teams = db.Column(db.Integer)
    min_team_size = db.Column(db.Integer, default=1)
    max_team_size = db.Column(db.Integer, default=4)
    
    stages = db.relationship('Stage', backref='hackathon', lazy=True)
    teams = db.relationship('Team', backref='hackathon', lazy=True)
    problem_statements = db.relationship('ProblemStatement', backref='hackathon', lazy=True)

class ProblemStatement(db.Model):
    __tablename__ = 'problem_statements'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    pdf_file_path = db.Column(db.String(255), nullable=False) # File system path
    max_team_limit = db.Column(db.Integer, default=50) # Just in case limit per problem is needed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Stage(db.Model):
    __tablename__ = 'stages'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    weightage = db.Column(db.Float, nullable=False) # e.g. 30.0 for 30%
    order_index = db.Column(db.Integer, default=0)
    
class Team(db.Model):
    __tablename__ = 'teams'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_closed = db.Column(db.Boolean, default=False)
    problem_statement_id = db.Column(db.Integer, db.ForeignKey('problem_statements.id'), nullable=True)
    
    members = db.relationship('TeamMember', backref='team', lazy=True)
    problem_statement = db.relationship('ProblemStatement', backref='teams', lazy=True)
    
class TeamMember(db.Model):
    __tablename__ = 'team_members'
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    user = db.relationship('User', backref='team_memberships')

class Evaluation(db.Model):
    __tablename__ = 'evaluations'
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    stage_id = db.Column(db.Integer, db.ForeignKey('stages.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    comments = db.Column(db.Text)

class FacultyAssignment(db.Model):
    __tablename__ = 'faculty_assignments'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

class QRLog(db.Model):
    __tablename__ = 'qr_logs'
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scanned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scan_type = db.Column(db.String(20), nullable=False) # REGISTRATION, MEAL
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.String(200))

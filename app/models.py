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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    
    # Meal Config
    enable_breakfast = db.Column(db.Boolean, default=False)
    enable_lunch = db.Column(db.Boolean, default=False)
    enable_dinner = db.Column(db.Boolean, default=False)
    
    # Meal Times (duration: start_time to start_time + 1 hour)
    # Format: HH:MM (24-hour format), relative to hackathon start_date
    breakfast_time = db.Column(db.String(5), nullable=True)  # e.g., "07:00"
    lunch_time = db.Column(db.String(5), nullable=True)      # e.g., "12:30"
    dinner_time = db.Column(db.String(5), nullable=True)     # e.g., "18:00"
    
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

class EvaluationCriteria(db.Model):
    __tablename__ = 'evaluation_criteria'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    is_enabled = db.Column(db.Boolean, default=False)

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
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Legacy/compat fields (some existing DBs require these)
    stage_id = db.Column(db.Integer, nullable=False, default=1)
    score = db.Column(db.Float, nullable=False, default=0.0)
    comments = db.Column(db.Text, nullable=True)
    
    innovation_score = db.Column(db.Integer, nullable=True) # made nullable to support flexible criteria
    technical_score = db.Column(db.Integer, nullable=True)
    uiux_score = db.Column(db.Integer, nullable=True)
    practicality_score = db.Column(db.Integer, nullable=True)
    presentation_score = db.Column(db.Integer, nullable=True) # Added new field
    total_score = db.Column(db.Float, nullable=False) # Changed to float for weighted calc
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('team_id', 'faculty_id', name='uq_team_faculty_evaluation'),
    )

class FacultyAssignment(db.Model):
    __tablename__ = 'faculty_assignments'
    id = db.Column(db.Integer, primary_key=True)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('hackathon_id', 'faculty_id', name='uq_hackathon_faculty_assignment'),
    )

class QRLog(db.Model):
    __tablename__ = 'qr_logs'
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scanned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scan_type = db.Column(db.String(20), nullable=False) # REGISTRATION, MEAL
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.String(200))

class TeamQR(db.Model):
    __tablename__ = 'team_qrs'
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False)
    qr_type = db.Column(db.String(20), nullable=False) # 'ACCESS', 'DINNER'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('team_id', 'qr_type', name='uq_team_qr_type'),
    )

class TeamMealUsage(db.Model):
    __tablename__ = 'team_meal_usage'
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    meal_type = db.Column(db.String(20), nullable=False) # 'DINNER', 'LUNCH', 'BREAKFAST'
    used_count = db.Column(db.Integer, default=0)
    usage_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('team_id', 'meal_type', 'usage_date', name='uq_team_meal_daily_usage'),
    )


class QRFoodTicketStatus(enum.Enum):
    """Status of a food ticket QR code"""
    ACTIVE = 'ACTIVE'          # Valid and ready to scan
    USED = 'USED'              # Already scanned (ticket consumed)
    EXPIRED = 'EXPIRED'        # Past hackathon end date or invalidated
    REVOKED = 'REVOKED'        # Manually invalidated by admin


class QRFoodTicket(db.Model):
    """
    QR-based food ticket for team members.
    Each team member gets a unique QR code per meal type.
    Status transitions: ACTIVE -> USED -> (next ACTIVE generated)
    """
    __tablename__ = 'qr_food_tickets'
    id = db.Column(db.Integer, primary_key=True)
    
    # Core relationships (reuse existing identifiers)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team_member_id = db.Column(db.Integer, db.ForeignKey('team_members.id'), nullable=False)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    
    # QR metadata
    qr_token = db.Column(db.String(256), unique=True, nullable=False)  # Unique per ticket
    meal_type = db.Column(db.String(20), nullable=False)  # BREAKFAST, LUNCH, DINNER
    status = db.Column(db.Enum(QRFoodTicketStatus), default=QRFoodTicketStatus.ACTIVE, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    scanned_at = db.Column(db.DateTime, nullable=True)  # When this ticket was used
    expires_at = db.Column(db.DateTime, nullable=True)  # When ticket becomes invalid
    
    # Relationships
    team_member = db.relationship('TeamMember', backref='food_tickets')
    hackathon = db.relationship('Hackathon', backref='food_tickets')
    
    __table_args__ = (
        # Ensure only ONE active ticket per team member per meal type
        db.UniqueConstraint(
            'team_member_id',
            'meal_type',
            'status',
            name='uq_active_ticket_per_member_meal'
        ),
        # Index for fast QR token lookups
        db.Index('ix_qr_token', 'qr_token'),
        # Index for finding active tickets
        db.Index('ix_meal_status_active', 'meal_type', 'status'),
    )


class QRScanLog(db.Model):
    """
    Audit log for all QR scan attempts (success or failure).
    Prevents double-scanning and provides complete audit trail.
    """
    __tablename__ = 'qr_scan_logs'
    id = db.Column(db.Integer, primary_key=True)
    
    # References
    qr_ticket_id = db.Column(db.Integer, db.ForeignKey('qr_food_tickets.id'), nullable=False)
    team_member_id = db.Column(db.Integer, db.ForeignKey('team_members.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    hackathon_id = db.Column(db.Integer, db.ForeignKey('hackathons.id'), nullable=False)
    
    # Scanner information (who scanned this)
    scanned_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for QR kiosk
    
    # Scan details
    scan_status = db.Column(db.String(20), nullable=False)  # SUCCESS, ALREADY_USED, INVALID_TOKEN, EXPIRED, etc
    scan_reason = db.Column(db.String(255), nullable=True)  # Error message if failed
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    qr_ticket = db.relationship('QRFoodTicket', backref='scan_logs')
    team_member = db.relationship('TeamMember', backref='qr_scans')
    scanned_by_user = db.relationship('User', backref='scanned_qrs')
    
    __table_args__ = (
        # Ensure single successful scan per ticket (idempotency)
        db.UniqueConstraint(
            'qr_ticket_id',
            'scan_status',
            name='uq_one_success_per_ticket'
        ),
        # Index for audit queries
        db.Index('ix_scan_timestamp', 'scanned_at'),
        db.Index('ix_scan_status', 'scan_status'),
    )

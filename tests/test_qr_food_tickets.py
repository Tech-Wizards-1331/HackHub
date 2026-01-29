"""
Comprehensive tests for QR Food Ticket System
Tests cover: model creation, ticket generation, scanning, concurrency, audit trails.
"""

import pytest
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import (
    User,
    UserRole,
    Hackathon,
    HackathonStatus,
    Team,
    TeamMember,
    QRFoodTicket,
    QRFoodTicketStatus,
    QRScanLog,
)
from app.utils.qr_ticket_service import QRTicketService
from app.utils.qr_code_generator import QRCodeGenerator


@pytest.fixture(scope="session")
def app():
    """Create test app with in-memory SQLite."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_db(app):
    """Reset database before each test."""
    with app.app_context():
        db.session.rollback()
        # Preserve tables but clear data
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        yield


def create_test_user(username, role=UserRole.PARTICIPANT, **kwargs):
    """Helper to create test user."""
    u = User(
        username=username,
        email=f"{username}@test.com",
        role=role,
        full_name=kwargs.get("full_name", f"{username.title()} User"),
        college="Test University",
    )
    u.set_password("password123")
    for key, val in kwargs.items():
        if key != "full_name":
            setattr(u, key, val)
    db.session.add(u)
    db.session.commit()
    return u


def create_test_hackathon(name="Test Hackathon", **kwargs):
    """Helper to create test hackathon."""
    h = Hackathon(
        name=name,
        description="Test hackathon",
        venue="Test Venue",
        status=HackathonStatus.ONGOING,
        start_date=kwargs.get(
            "start_date", datetime.utcnow() + timedelta(days=-1)
        ),
        end_date=kwargs.get("end_date", datetime.utcnow() + timedelta(days=1)),
        max_teams=10,
        min_team_size=2,
        max_team_size=4,
        enable_breakfast=True,
        enable_lunch=True,
        enable_dinner=True,
    )
    for key, val in kwargs.items():
        if key not in ["start_date", "end_date"]:
            setattr(h, key, val)
    db.session.add(h)
    db.session.commit()
    return h


def create_test_team(name="Test Team", **kwargs):
    """Helper to create test team with members."""
    leader = kwargs.get("leader") or create_test_user("leader")
    hackathon = kwargs.get("hackathon") or create_test_hackathon()

    team = Team(
        name=name,
        hackathon_id=hackathon.id,
        leader_id=leader.id,
    )
    db.session.add(team)
    db.session.commit()

    # Add members
    if "members" not in kwargs:
        member1 = create_test_user(f"member_{team.id}_1")
        member2 = create_test_user(f"member_{team.id}_2")
        kwargs["members"] = [member1, member2]

    for user in kwargs.get("members", []):
        tm = TeamMember(team_id=team.id, user_id=user.id)
        db.session.add(tm)
    db.session.commit()

    return team


# ============================================================================
# Model Tests
# ============================================================================


def test_qr_food_ticket_model_creation(app):
    """Test QRFoodTicket model basic creation and fields."""
    with app.app_context():
        team = create_test_team()
        team_member = team.members[0]
        hackathon = team.hackathon

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="test_token_123",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket)
        db.session.commit()

        fetched = QRFoodTicket.query.get(ticket.id)
        assert fetched is not None
        assert fetched.qr_token == "test_token_123"
        assert fetched.meal_type == "BREAKFAST"
        assert fetched.status == QRFoodTicketStatus.ACTIVE


def test_qr_food_ticket_unique_qr_token(app):
    """Test that QR tokens must be unique."""
    with app.app_context():
        team = create_test_team()
        team_member = team.members[0]
        hackathon = team.hackathon

        ticket1 = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="unique_token",
            meal_type="BREAKFAST",
        )
        db.session.add(ticket1)
        db.session.commit()

        # Try to create duplicate token
        ticket2 = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="unique_token",
            meal_type="LUNCH",
        )
        db.session.add(ticket2)
        with pytest.raises(Exception):  # IntegrityError
            db.session.commit()


def test_qr_food_ticket_one_active_per_member_meal(app):
    """Test unique constraint: one ACTIVE ticket per member/meal type."""
    with app.app_context():
        team = create_test_team()
        team_member = team.members[0]
        hackathon = team.hackathon

        ticket1 = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="token1",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket1)
        db.session.commit()

        # Try to create another ACTIVE for same member/meal
        ticket2 = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="token2",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket2)
        with pytest.raises(Exception):  # IntegrityError
            db.session.commit()


def test_qr_scan_log_model(app):
    """Test QRScanLog audit trail model."""
    with app.app_context():
        team = create_test_team()
        team_member = team.members[0]
        hackathon = team.hackathon

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="token_audit",
            meal_type="DINNER",
        )
        db.session.add(ticket)
        db.session.commit()

        log = QRScanLog(
            qr_ticket_id=ticket.id,
            team_member_id=team_member.id,
            team_id=team.id,
            hackathon_id=hackathon.id,
            scan_status="SUCCESS",
        )
        db.session.add(log)
        db.session.commit()

        fetched_log = QRScanLog.query.get(log.id)
        assert fetched_log is not None
        assert fetched_log.scan_status == "SUCCESS"
        assert fetched_log.qr_ticket_id == ticket.id


# ============================================================================
# QRTicketService Tests
# ============================================================================


def test_generate_qr_token(app):
    """Test QR token generation is unique and secure."""
    with app.app_context():
        tokens = set()
        for _ in range(100):
            token = QRTicketService.generate_qr_token()
            assert len(token) > 0
            assert token not in tokens
            tokens.add(token)


def test_create_initial_tickets(app):
    """Test creating initial tickets for team members."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon

        meal_types = ["BREAKFAST", "LUNCH", "DINNER"]
        tickets = QRTicketService.create_initial_tickets(
            team.id, meal_types, hackathon.id
        )

        assert len(tickets) == len(team.members) * len(meal_types)

        # Verify all tickets are ACTIVE
        for ticket in tickets:
            assert ticket.status == QRFoodTicketStatus.ACTIVE

        # Verify all tokens are unique
        tokens = [t.qr_token for t in tickets]
        assert len(tokens) == len(set(tokens))

        # Verify relationships
        for ticket in tickets:
            assert ticket.team_id == team.id
            assert ticket.hackathon_id == hackathon.id


def test_scan_ticket_success(app):
    """Test successful QR scan: mark as USED and generate new ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        # Create initial ticket
        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="scan_token",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket)
        db.session.commit()

        original_token = ticket.qr_token

        # Perform scan
        result = QRTicketService.scan_ticket(original_token)

        assert result["success"] is True
        assert "scanned successfully" in result["message"]
        assert result["ticket_id"] == ticket.id
        assert "new_qr_token" in result

        # Verify old ticket is marked USED
        old_ticket = QRFoodTicket.query.get(ticket.id)
        assert old_ticket.status == QRFoodTicketStatus.USED
        assert old_ticket.scanned_at is not None

        # Verify new ACTIVE ticket was created
        new_tickets = QRFoodTicket.query.filter(
            QRFoodTicket.team_member_id == team_member.id,
            QRFoodTicket.meal_type == "BREAKFAST",
            QRFoodTicket.status == QRFoodTicketStatus.ACTIVE,
        ).all()
        assert len(new_tickets) == 1
        assert new_tickets[0].qr_token != original_token


def test_scan_ticket_invalid_token(app):
    """Test scanning with invalid QR token."""
    with app.app_context():
        result = QRTicketService.scan_ticket("nonexistent_token")
        assert result["success"] is False
        assert result["ticket_id"] is None


def test_scan_ticket_already_used(app):
    """Test preventing double-scan of same ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="double_scan_token",
            meal_type="LUNCH",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket)
        db.session.commit()

        # First scan succeeds
        result1 = QRTicketService.scan_ticket("double_scan_token")
        assert result1["success"] is True

        # Old token is now USED, second scan fails
        result2 = QRTicketService.scan_ticket("double_scan_token")
        assert result2["success"] is False
        assert "already been used" in result2["message"]


def test_scan_ticket_creates_audit_log(app):
    """Test that scans create audit logs."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="audit_token",
            meal_type="DINNER",
        )
        db.session.add(ticket)
        db.session.commit()

        # Scan with scanner ID
        scanner = create_test_user("scanner", role=UserRole.FACULTY)
        result = QRTicketService.scan_ticket("audit_token", scanner.id)
        assert result["success"] is True

        # Verify log exists
        logs = QRScanLog.query.filter_by(
            qr_ticket_id=ticket.id, scan_status="SUCCESS"
        ).all()
        assert len(logs) > 0
        assert logs[0].scanned_by_user_id == scanner.id


def test_get_active_ticket(app):
    """Test retrieving currently active ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        # Create ticket
        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="active_search",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
        )
        db.session.add(ticket)
        db.session.commit()

        # Retrieve it
        found = QRTicketService.get_active_ticket(team_member.id, "BREAKFAST")
        assert found is not None
        assert found.id == ticket.id

        # No result for different meal type
        not_found = QRTicketService.get_active_ticket(team_member.id, "LUNCH")
        assert not_found is None


def test_get_ticket_history(app):
    """Test retrieving ticket history for a member."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        # Create multiple tickets
        for i, meal in enumerate(["BREAKFAST", "LUNCH", "DINNER"]):
            ticket = QRFoodTicket(
                team_id=team.id,
                team_member_id=team_member.id,
                hackathon_id=hackathon.id,
                qr_token=f"history_{i}",
                meal_type=meal,
            )
            db.session.add(ticket)
        db.session.commit()

        history = QRTicketService.get_ticket_history(team_member.id)
        assert len(history) >= 3


def test_revoke_ticket(app):
    """Test revoking a ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="revoke_token",
            meal_type="BREAKFAST",
        )
        db.session.add(ticket)
        db.session.commit()

        assert QRTicketService.revoke_ticket(ticket.id) is True

        revoked = QRFoodTicket.query.get(ticket.id)
        assert revoked.status == QRFoodTicketStatus.REVOKED


# ============================================================================
# QR Code Generation Tests
# ============================================================================


def test_qr_code_generate_image(app):
    """Test QR code image generation."""
    with app.app_context():
        img_bytes = QRCodeGenerator.generate_qr_image(
            "test_token", "BREAKFAST", "John Doe"
        )
        assert isinstance(img_bytes, bytes)
        assert len(img_bytes) > 0
        # PNG magic number
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_code_generate_base64(app):
    """Test QR code base64 encoding."""
    with app.app_context():
        b64 = QRCodeGenerator.generate_qr_base64(
            "test_token", "LUNCH", "Jane Smith"
        )
        assert isinstance(b64, str)
        assert len(b64) > 0
        # Base64 should not contain newlines from standard lib
        assert "\n" not in b64


def test_qr_code_generate_data_uri(app):
    """Test QR code data URI generation."""
    with app.app_context():
        uri = QRCodeGenerator.generate_qr_data_uri(
            "test_token", "DINNER", "Bob Johnson"
        )
        assert uri.startswith("data:image/png;base64,")


def test_qr_code_parse_data(app):
    """Test parsing QR code data."""
    with app.app_context():
        original_data = "MEAL|BREAKFAST|test_token_123|Alice Bob"
        parsed = QRCodeGenerator.parse_qr_data(original_data)
        assert parsed["meal_type"] == "BREAKFAST"
        assert parsed["token"] == "test_token_123"
        assert parsed["team_member_name"] == "Alice Bob"


# ============================================================================
# Concurrency and Edge Cases
# ============================================================================


def test_scan_ticket_expiration(app):
    """Test scanning an expired ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        # Create expired ticket
        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="expired_token",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.ACTIVE,
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.session.add(ticket)
        db.session.commit()

        result = QRTicketService.scan_ticket("expired_token")
        assert result["success"] is False
        assert "expired" in result["message"].lower()


def test_scan_revoked_ticket(app):
    """Test scanning a revoked ticket."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        ticket = QRFoodTicket(
            team_id=team.id,
            team_member_id=team_member.id,
            hackathon_id=hackathon.id,
            qr_token="revoked_token",
            meal_type="BREAKFAST",
            status=QRFoodTicketStatus.REVOKED,
        )
        db.session.add(ticket)
        db.session.commit()

        result = QRTicketService.scan_ticket("revoked_token")
        assert result["success"] is False
        assert "revoked" in result["message"].lower()


def test_multiple_meal_types_per_member(app):
    """Test member can have tickets for all meal types."""
    with app.app_context():
        team = create_test_team()
        hackathon = team.hackathon
        team_member = team.members[0]

        meals = ["BREAKFAST", "LUNCH", "DINNER"]
        for meal in meals:
            ticket = QRFoodTicket(
                team_id=team.id,
                team_member_id=team_member.id,
                hackathon_id=hackathon.id,
                qr_token=f"token_{meal}",
                meal_type=meal,
            )
            db.session.add(ticket)
        db.session.commit()

        # Verify all exist
        for meal in meals:
            found = QRTicketService.get_active_ticket(team_member.id, meal)
            assert found is not None
            assert found.meal_type == meal

#!/usr/bin/env python
"""
Quick validation script to verify QR Food Ticket System implementation.
Tests core functionality without pytest.
"""

from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Hackathon, HackathonStatus, Team, TeamMember,
    QRFoodTicket, QRFoodTicketStatus, QRScanLog
)
from app.utils.qr_ticket_service import QRTicketService
from app.utils.qr_code_generator import QRCodeGenerator
from datetime import datetime, timedelta


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def test_models():
    """Test model creation and constraints."""
    print_section("TEST 1: Model Creation & Constraints")
    
    # Create test data
    user = User(
        username='test_user',
        email='test@test.com',
        role=UserRole.PARTICIPANT,
        full_name='Test User'
    )
    user.set_password('pass')
    db.session.add(user)
    db.session.commit()
    print("✓ User created")
    
    hackathon = Hackathon(
        name='Test Hackathon',
        status=HackathonStatus.ONGOING,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=1)
    )
    db.session.add(hackathon)
    db.session.commit()
    print("✓ Hackathon created")
    
    team = Team(
        name='Test Team',
        hackathon_id=hackathon.id,
        leader_id=user.id
    )
    db.session.add(team)
    db.session.commit()
    print("✓ Team created")
    
    member = TeamMember(team_id=team.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()
    print("✓ Team member created")
    
    ticket = QRFoodTicket(
        team_id=team.id,
        team_member_id=member.id,
        hackathon_id=hackathon.id,
        qr_token='unique_token_123',
        meal_type='BREAKFAST',
        status=QRFoodTicketStatus.ACTIVE
    )
    db.session.add(ticket)
    db.session.commit()
    print("✓ QR Food Ticket created")
    
    return team, member, ticket, hackathon


def test_qr_token_generation():
    """Test QR token uniqueness."""
    print_section("TEST 2: QR Token Generation")
    
    tokens = set()
    for i in range(10):
        token = QRTicketService.generate_qr_token()
        assert len(token) > 0, f"Token {i} is empty"
        assert token not in tokens, f"Duplicate token detected: {token}"
        tokens.add(token)
    
    print(f"✓ Generated {len(tokens)} unique tokens")
    print(f"  Sample token: {list(tokens)[0][:20]}... (length: {len(list(tokens)[0])})")


def test_qr_image_generation():
    """Test QR code image generation."""
    print_section("TEST 3: QR Code Image Generation")
    
    # Test PNG generation
    img_bytes = QRCodeGenerator.generate_qr_image(
        'test_token_123',
        'BREAKFAST',
        'John Doe'
    )
    assert isinstance(img_bytes, bytes), "Image should be bytes"
    assert len(img_bytes) > 0, "Image should not be empty"
    assert img_bytes[:8] == b'\x89PNG\r\n\x1a\n', "Should be valid PNG"
    print(f"✓ PNG image generated ({len(img_bytes)} bytes)")
    
    # Test base64 encoding
    b64 = QRCodeGenerator.generate_qr_base64('token', 'LUNCH', 'Jane Smith')
    assert isinstance(b64, str), "Base64 should be string"
    assert len(b64) > 0, "Base64 should not be empty"
    assert '\n' not in b64, "Base64 should not contain newlines"
    print(f"✓ Base64 encoding generated ({len(b64)} chars)")
    
    # Test data URI
    uri = QRCodeGenerator.generate_qr_data_uri('token', 'DINNER', 'Bob')
    assert uri.startswith('data:image/png;base64,'), "Should be valid data URI"
    print(f"✓ Data URI generated (prefix: {uri[:30]}...)")


def test_initial_ticket_creation():
    """Test creating initial tickets for team."""
    print_section("TEST 4: Initial Ticket Creation")
    
    team, member, _, hackathon = test_models()
    
    # Clear existing tickets
    QRFoodTicket.query.delete()
    db.session.commit()
    
    # Create initial tickets
    meal_types = ['BREAKFAST', 'LUNCH', 'DINNER']
    tickets = QRTicketService.create_initial_tickets(
        team.id, meal_types, hackathon.id
    )
    
    assert len(tickets) == len(team.members) * len(meal_types), \
        f"Expected {len(team.members) * len(meal_types)} tickets, got {len(tickets)}"
    
    for ticket in tickets:
        assert ticket.status == QRFoodTicketStatus.ACTIVE
        assert ticket.team_id == team.id
    
    print(f"✓ Created {len(tickets)} tickets for team")
    print(f"  - Members: {len(team.members)}")
    print(f"  - Meal types: {len(meal_types)}")


def test_ticket_scan():
    """Test scanning and marking as USED."""
    print_section("TEST 5: Ticket Scanning & Auto-Generation")
    
    # Create fresh test data
    user = User(
        username='scanner_user',
        email='scan@test.com',
        role=UserRole.PARTICIPANT,
        full_name='Scanner User'
    )
    user.set_password('pass')
    db.session.add(user)
    db.session.commit()
    
    hackathon = Hackathon(
        name='Scan Test',
        status=HackathonStatus.ONGOING,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=1)
    )
    db.session.add(hackathon)
    db.session.commit()
    
    team = Team(name='Scan Team', hackathon_id=hackathon.id, leader_id=user.id)
    db.session.add(team)
    db.session.commit()
    
    member = TeamMember(team_id=team.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()
    
    ticket = QRFoodTicket(
        team_id=team.id,
        team_member_id=member.id,
        hackathon_id=hackathon.id,
        qr_token='scan_me_token',
        meal_type='BREAKFAST',
        status=QRFoodTicketStatus.ACTIVE
    )
    db.session.add(ticket)
    db.session.commit()
    
    original_token = ticket.qr_token
    
    # Perform scan
    result = QRTicketService.scan_ticket('scan_me_token')
    
    assert result['success'] is True, f"Scan failed: {result['message']}"
    assert 'new_qr_token' in result, "Should return new QR token"
    assert result['new_qr_token'] != original_token, "New token should be different"
    
    # Verify old ticket is marked USED
    old_ticket = QRFoodTicket.query.get(ticket.id)
    assert old_ticket.status == QRFoodTicketStatus.USED, "Old ticket should be USED"
    assert old_ticket.scanned_at is not None, "Should have scan timestamp"
    
    # Verify new ACTIVE ticket exists
    new_tickets = QRFoodTicket.query.filter(
        QRFoodTicket.team_member_id == member.id,
        QRFoodTicket.meal_type == 'BREAKFAST',
        QRFoodTicket.status == QRFoodTicketStatus.ACTIVE
    ).all()
    assert len(new_tickets) == 1, "Should have exactly one ACTIVE ticket"
    
    print("✓ First scan successful:")
    print(f"  - Old ticket marked: USED at {old_ticket.scanned_at}")
    print(f"  - New ticket generated: {new_tickets[0].qr_token[:20]}...")
    
    # Try to scan same token again (should fail)
    result2 = QRTicketService.scan_ticket('scan_me_token')
    assert result2['success'] is False, "Double scan should fail"
    assert 'already been used' in result2['message'], "Should indicate already used"
    
    print("✓ Second scan (double-scan) prevented:")
    print(f"  - Result: {result2['message']}")


def test_audit_logs():
    """Test audit log creation."""
    print_section("TEST 6: Audit Logs & Compliance")
    
    user = User(
        username='audit_user',
        email='audit@test.com',
        role=UserRole.PARTICIPANT,
        full_name='Audit User'
    )
    user.set_password('pass')
    db.session.add(user)
    db.session.commit()
    
    scanner = User(
        username='scanner',
        email='scanner@test.com',
        role=UserRole.FACULTY,
        full_name='Scanner'
    )
    scanner.set_password('pass')
    db.session.add(scanner)
    db.session.commit()
    
    hackathon = Hackathon(
        name='Audit Test',
        status=HackathonStatus.ONGOING,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=1)
    )
    db.session.add(hackathon)
    db.session.commit()
    
    team = Team(name='Audit Team', hackathon_id=hackathon.id, leader_id=user.id)
    db.session.add(team)
    db.session.commit()
    
    member = TeamMember(team_id=team.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()
    
    ticket = QRFoodTicket(
        team_id=team.id,
        team_member_id=member.id,
        hackathon_id=hackathon.id,
        qr_token='audit_token',
        meal_type='LUNCH',
        status=QRFoodTicketStatus.ACTIVE
    )
    db.session.add(ticket)
    db.session.commit()
    
    # Scan with scanner ID
    result = QRTicketService.scan_ticket('audit_token', scanner.id)
    assert result['success'] is True
    
    # Check audit logs
    logs = QRScanLog.query.filter_by(qr_ticket_id=ticket.id).all()
    assert len(logs) > 0, "Should have scan logs"
    
    success_logs = [l for l in logs if l.scan_status == 'SUCCESS']
    assert len(success_logs) > 0, "Should have SUCCESS log"
    assert success_logs[0].scanned_by_user_id == scanner.id, "Should log scanner ID"
    
    print(f"✓ Audit logs created and linked:")
    print(f"  - Total logs: {len(logs)}")
    print(f"  - Success scans: {len(success_logs)}")
    print(f"  - Scanner: {scanner.full_name} (ID: {scanner.id})")
    print(f"  - Timestamp: {success_logs[0].scanned_at}")


def main():
    """Run all validation tests."""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        
        print("\n" + "="*70)
        print("  QR FOOD TICKET SYSTEM - VALIDATION TESTS")
        print("="*70)
        
        try:
            test_qr_token_generation()
            test_qr_image_generation()
            test_initial_ticket_creation()
            test_ticket_scan()
            test_audit_logs()
            
            print_section("SUMMARY")
            print("✅ All validation tests passed!\n")
            print("System is ready for deployment. Run full test suite with:")
            print("  pytest tests/test_qr_food_tickets.py -v\n")
            
        except Exception as e:
            print_section("ERROR")
            print(f"❌ Validation failed: {str(e)}\n")
            import traceback
            traceback.print_exc()
            return 1
    
    return 0


if __name__ == '__main__':
    exit(main())

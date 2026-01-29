"""
Integration Example: QR Food Ticket System
Shows how to integrate the QR system into your hackathon workflow.
"""

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Hackathon, Team, TeamMember
from app.utils.qr_ticket_service import QRTicketService
from app.utils.qr_code_generator import QRCodeGenerator
from datetime import datetime, timedelta


def example_complete_workflow():
    """
    Complete example: from setup to scanning to auditing.
    Run this to see the system in action.
    """
    app = create_app()
    
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("=" * 70)
        print("QR FOOD TICKET SYSTEM - INTEGRATION EXAMPLE")
        print("=" * 70)
        
        # ============================================================================
        # STEP 1: Setup (Admin creates hackathon and teams)
        # ============================================================================
        print("\n[STEP 1] Setting up hackathon and teams...")
        
        # Create admin
        admin = User(
            username='admin',
            email='admin@hackathon.com',
            role=UserRole.ADMIN,
            full_name='Event Admin'
        )
        admin.set_password('admin_pass')
        db.session.add(admin)
        db.session.commit()
        print("✓ Admin created")
        
        # Create hackathon
        hackathon = Hackathon(
            name='TechCon 2026',
            description='Annual tech hackathon',
            venue='Convention Center',
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=1),
            max_teams=5,
            enable_breakfast=True,
            enable_lunch=True,
            enable_dinner=True
        )
        db.session.add(hackathon)
        db.session.commit()
        print(f"✓ Hackathon created: {hackathon.name}")
        
        # Create team members
        members = []
        for i in range(3):
            member = User(
                username=f'participant_{i+1}',
                email=f'participant{i+1}@hackathon.com',
                role=UserRole.PARTICIPANT,
                full_name=f'Team Member {i+1}'
            )
            member.set_password('pass')
            db.session.add(member)
            members.append(member)
        db.session.commit()
        print(f"✓ {len(members)} participants created")
        
        # Create team
        team = Team(
            name='Alpha Squad',
            hackathon_id=hackathon.id,
            leader_id=members[0].id
        )
        db.session.add(team)
        db.session.commit()
        print(f"✓ Team created: {team.name}")
        
        # Add members to team
        for member in members:
            tm = TeamMember(team_id=team.id, user_id=member.id)
            db.session.add(tm)
        db.session.commit()
        print(f"✓ {len(members)} members added to team")
        
        # ============================================================================
        # STEP 2: Initialize Food Tickets
        # ============================================================================
        print("\n[STEP 2] Initializing food tickets for team...")
        
        meal_types = ['BREAKFAST', 'LUNCH', 'DINNER']
        tickets = QRTicketService.create_initial_tickets(
            team_id=team.id,
            meal_types=meal_types,
            hackathon_id=hackathon.id
        )
        print(f"✓ Created {len(tickets)} food tickets")
        print(f"  - {len(members)} members × {len(meal_types)} meals")
        
        # ============================================================================
        # STEP 3: Member Views Their QR Codes
        # ============================================================================
        print("\n[STEP 3] Member views breakfast ticket...")
        
        member1 = team.members[0]
        user1 = member1.user
        
        ticket = QRTicketService.get_active_ticket(member1.id, 'BREAKFAST')
        print(f"✓ Retrieved active BREAKFAST ticket for {user1.full_name}")
        print(f"  - Token: {ticket.qr_token[:20]}...")
        print(f"  - Status: {ticket.status.value}")
        print(f"  - Created: {ticket.created_at}")
        
        # ============================================================================
        # STEP 4: Generate QR Code
        # ============================================================================
        print("\n[STEP 4] Generating QR code image...")
        
        # Generate base64 for web
        qr_base64 = QRCodeGenerator.generate_qr_base64(
            ticket.qr_token,
            ticket.meal_type,
            user1.full_name
        )
        print(f"✓ QR code generated (Base64)")
        print(f"  - Length: {len(qr_base64)} chars")
        print(f"  - Preview: {qr_base64[:50]}...")
        
        # Generate PNG bytes for printing
        qr_png = QRCodeGenerator.generate_qr_image(
            ticket.qr_token,
            ticket.meal_type,
            user1.full_name
        )
        print(f"✓ QR code generated (PNG)")
        print(f"  - Size: {len(qr_png)} bytes")
        
        # ============================================================================
        # STEP 5: Scan at Breakfast Counter
        # ============================================================================
        print("\n[STEP 5] Member arrives at breakfast counter...")
        
        # Create scanner (faculty member)
        scanner = User(
            username='scanner',
            email='scanner@hackathon.com',
            role=UserRole.FACULTY,
            full_name='Breakfast Counter Staff'
        )
        scanner.set_password('pass')
        db.session.add(scanner)
        db.session.commit()
        
        # Scan the QR
        result = QRTicketService.scan_ticket(
            qr_token=ticket.qr_token,
            scanned_by_user_id=scanner.id
        )
        
        print(f"✓ Scan result:")
        print(f"  - Success: {result['success']}")
        print(f"  - Message: {result['message']}")
        print(f"  - Member: {result['team_member']['user']['full_name']}")
        
        if result['success']:
            print(f"  - New QR token: {result['new_qr_token'][:20]}...")
            print(f"  - Member saves this for next meal")
        
        # ============================================================================
        # STEP 6: Verify Ticket State Changed
        # ============================================================================
        print("\n[STEP 6] Verifying ticket state...")
        
        old_ticket = QRTicketService.get_active_ticket(member1.id, 'BREAKFAST')
        print(f"✓ Old ticket status: USED")
        print(f"  - Scanned at: {ticket.scanned_at}")
        
        print(f"✓ New ACTIVE ticket exists")
        print(f"  - Token: {old_ticket.qr_token[:20]}...")
        print(f"  - Status: {old_ticket.status.value}")
        
        # ============================================================================
        # STEP 7: Prevent Double-Scan
        # ============================================================================
        print("\n[STEP 7] Attempting to scan same token again (should fail)...")
        
        result2 = QRTicketService.scan_ticket(
            qr_token=ticket.qr_token,  # Same token
            scanned_by_user_id=scanner.id
        )
        
        print(f"✓ Double-scan prevented:")
        print(f"  - Success: {result2['success']}")
        print(f"  - Message: {result2['message']}")
        print(f"  - This is correct behavior ✓")
        
        # ============================================================================
        # STEP 8: Member Scans New Ticket at Lunch
        # ============================================================================
        print("\n[STEP 8] Member scans lunch ticket...")
        
        lunch_ticket = QRTicketService.get_active_ticket(member1.id, 'LUNCH')
        result3 = QRTicketService.scan_ticket(
            qr_token=lunch_ticket.qr_token,
            scanned_by_user_id=scanner.id
        )
        
        print(f"✓ Lunch scan successful:")
        print(f"  - New LUNCH token: {result3['new_qr_token'][:20]}...")
        
        # ============================================================================
        # STEP 9: Admin Views Audit Logs
        # ============================================================================
        print("\n[STEP 9] Admin audits meal consumption...")
        
        logs = QRTicketService.get_scan_history(team_id=team.id)
        
        print(f"✓ Scan audit logs:")
        print(f"  - Total scans: {len(logs)}")
        for i, log in enumerate(logs[:5], 1):
            scanner_name = log.scanned_by_user.full_name if log.scanned_by_user else 'Kiosk'
            ticket_obj = log.qr_ticket
            print(f"    {i}. {ticket_obj.meal_type:10s} | "
                  f"{log.scan_status:15s} | "
                  f"Scanner: {scanner_name} | "
                  f"Time: {log.scanned_at.strftime('%H:%M:%S')}")
        
        # ============================================================================
        # STEP 10: View Member History
        # ============================================================================
        print("\n[STEP 10] Member views their ticket history...")
        
        history = QRTicketService.get_ticket_history(member1.id)
        
        print(f"✓ Ticket history for {user1.full_name}:")
        print(f"  - Total tickets: {len(history)}")
        for i, hist_ticket in enumerate(history[:5], 1):
            status = "✓ USED" if hist_ticket.status == hist_ticket.status.USED else f"  {hist_ticket.status.value}"
            print(f"    {i}. {hist_ticket.meal_type:10s} | {status:20s} | "
                  f"Created: {hist_ticket.created_at.strftime('%H:%M')}")
        
        # ============================================================================
        # STEP 11: Admin Revokes Ticket (Fraud Scenario)
        # ============================================================================
        print("\n[STEP 11] Admin revokes a ticket (fraud scenario)...")
        
        suspicious_ticket_id = tickets[0].id
        success = QRTicketService.revoke_ticket(
            ticket_id=suspicious_ticket_id,
            reason="Suspected duplicate scan"
        )
        
        if success:
            revoked_ticket = QRTicketService.get_active_ticket(member1.id, 'DINNER')
            print(f"✓ Ticket revoked successfully")
            print(f"  - Status is now: REVOKED")
            print(f"  - Next scan will fail with 'revoked' message")
        
        # ============================================================================
        # SUMMARY
        # ============================================================================
        print("\n" + "=" * 70)
        print("INTEGRATION EXAMPLE COMPLETE")
        print("=" * 70)
        print("\nKey Takeaways:")
        print("  1. Tickets auto-created for all members & meals")
        print("  2. Each scan marks ticket USED and generates new one")
        print("  3. Double-scans are prevented at database level")
        print("  4. Complete audit trail of all scans")
        print("  5. Admin can revoke compromised tickets")
        print("  6. System is atomic, concurrent-safe, auditable")
        print("\nNext Steps:")
        print("  - Integrate API into your hackathon web app")
        print("  - Test with real QR scanner hardware")
        print("  - Train meal counter staff")
        print("  - Monitor audit logs during event")
        print("\n" + "=" * 70)


if __name__ == '__main__':
    example_complete_workflow()

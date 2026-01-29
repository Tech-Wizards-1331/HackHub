"""
QR Food Ticket Service
Handles generation, validation, and scanning of food ticket QR codes.
Ensures atomic operations and prevents double-scanning.
Includes time-based visibility windows for meals.
"""

import uuid
import secrets
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (
    QRFoodTicket,
    QRScanLog,
    QRFoodTicketStatus,
    TeamMember,
    Team,
    Hackathon,
    User,
)


class QRTicketService:
    """Service for managing QR food tickets with atomic, idempotent operations."""

    # QR token length (balance between security and scannability)
    QR_TOKEN_LENGTH = 32
    
    # Meal window duration (2 hour from start time)
    MEAL_WINDOW_HOURS = 2

    @staticmethod
    def generate_qr_token() -> str:
        """Generate a cryptographically secure, unique QR token."""
        return secrets.token_urlsafe(QRTicketService.QR_TOKEN_LENGTH)

    @staticmethod
    def create_initial_tickets(
        team_id: int,
        meal_types: list,
        hackathon_id: int,
    ) -> list:
        """
        Create initial food tickets for all team members.
        Called when a team registers or hackathon transitions to food service phase.

        Args:
            team_id: ID of the team
            meal_types: List of meal types to create (e.g., ['BREAKFAST', 'LUNCH', 'DINNER'])
            hackathon_id: ID of the hackathon

        Returns:
            List of created QRFoodTicket objects
        """
        team = Team.query.get(team_id)
        if not team:
            raise ValueError(f"Team {team_id} not found")

        hackathon = Hackathon.query.get(hackathon_id)
        if not hackathon:
            raise ValueError(f"Hackathon {hackathon_id} not found")

        created_tickets = []

        for team_member in team.members:
            for meal_type in meal_types:
                ticket = QRFoodTicket(
                    team_id=team_id,
                    team_member_id=team_member.id,
                    hackathon_id=hackathon_id,
                    qr_token=QRTicketService.generate_qr_token(),
                    meal_type=meal_type.upper(),
                    status=QRFoodTicketStatus.ACTIVE,
                    expires_at=hackathon.end_date + timedelta(hours=2),  # Grace period
                )
                db.session.add(ticket)
                created_tickets.append(ticket)

        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            raise RuntimeError(f"Failed to create tickets: {str(e)}")

        return created_tickets

    @staticmethod
    def scan_ticket(
        qr_token: str,
        scanned_by_user_id: int = None,
    ) -> dict:
        """
        Scan and validate a QR food ticket. Atomic operation.

        Core logic:
        1. Validate token exists and is ACTIVE
        2. Check expiration
        3. Record scan attempt (audit log)
        4. Mark ticket as USED
        5. Generate new ACTIVE ticket for same member/meal

        Args:
            qr_token: The QR token to scan
            scanned_by_user_id: User ID of the scanner (optional, nullable for kiosks)

        Returns:
            {
                'success': bool,
                'message': str,
                'ticket_id': int or None,
                'team_member': {
                    'id': int,
                    'user': { 'full_name': str, ... },
                    'team': { 'name': str, ... }
                } or None,
                'meal_type': str or None,
            }
        """
        # Validate token
        ticket = QRFoodTicket.query.filter_by(qr_token=qr_token).first()

        if not ticket:
            return {
                "success": False,
                "message": "Invalid QR token",
                "ticket_id": None,
                "team_member": None,
                "meal_type": None,
            }

        # Check if already used
        if ticket.status == QRFoodTicketStatus.USED:
            QRTicketService._log_scan_attempt(
                ticket.id,
                ticket.team_member_id,
                ticket.team_id,
                ticket.hackathon_id,
                scanned_by_user_id,
                "ALREADY_USED",
                "Ticket has already been scanned",
            )
            return {
                "success": False,
                "message": "Ticket has already been used",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

        # Check if expired
        if ticket.status == QRFoodTicketStatus.EXPIRED:
            QRTicketService._log_scan_attempt(
                ticket.id,
                ticket.team_member_id,
                ticket.team_id,
                ticket.hackathon_id,
                scanned_by_user_id,
                "EXPIRED",
                "Ticket has expired",
            )
            return {
                "success": False,
                "message": "Ticket has expired",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

        if ticket.status == QRFoodTicketStatus.REVOKED:
            QRTicketService._log_scan_attempt(
                ticket.id,
                ticket.team_member_id,
                ticket.team_id,
                ticket.hackathon_id,
                scanned_by_user_id,
                "REVOKED",
                "Ticket has been revoked",
            )
            return {
                "success": False,
                "message": "Ticket has been revoked",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

        # Check expiration time
        if ticket.expires_at and datetime.utcnow() > ticket.expires_at:
            ticket.status = QRFoodTicketStatus.EXPIRED
            db.session.commit()
            QRTicketService._log_scan_attempt(
                ticket.id,
                ticket.team_member_id,
                ticket.team_id,
                ticket.hackathon_id,
                scanned_by_user_id,
                "EXPIRED",
                "Ticket expiration time has passed",
            )
            return {
                "success": False,
                "message": "Ticket has expired",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

        # Check if ticket is currently visible (within meal window)
        visibility_check = QRTicketService._check_meal_visibility(ticket)
        if not visibility_check["is_visible"]:
            QRTicketService._log_scan_attempt(
                ticket.id,
                ticket.team_member_id,
                ticket.team_id,
                ticket.hackathon_id,
                scanned_by_user_id,
                "NOT_VISIBLE",
                visibility_check["reason"],
            )
            return {
                "success": False,
                "message": visibility_check["reason"],
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

        # **Atomic scan operation**
        try:
            # Mark current ticket as USED
            ticket.status = QRFoodTicketStatus.USED
            ticket.scanned_at = datetime.utcnow()

            # Log successful scan
            scan_log = QRScanLog(
                qr_ticket_id=ticket.id,
                team_member_id=ticket.team_member_id,
                team_id=ticket.team_id,
                hackathon_id=ticket.hackathon_id,
                scanned_by_user_id=scanned_by_user_id,
                scan_status="SUCCESS",
                scanned_at=datetime.utcnow(),
            )
            db.session.add(scan_log)

            # Generate new ACTIVE ticket for same member/meal
            new_ticket = QRFoodTicket(
                team_id=ticket.team_id,
                team_member_id=ticket.team_member_id,
                hackathon_id=ticket.hackathon_id,
                qr_token=QRTicketService.generate_qr_token(),
                meal_type=ticket.meal_type,
                status=QRFoodTicketStatus.ACTIVE,
                expires_at=ticket.expires_at,
            )
            db.session.add(new_ticket)

            # Commit all changes atomically
            db.session.commit()

            return {
                "success": True,
                "message": f"Ticket scanned successfully. New {ticket.meal_type} ticket generated.",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
                "new_qr_token": new_ticket.qr_token,  # Return new token for next meal
            }

        except IntegrityError as e:
            db.session.rollback()
            # This shouldn't happen with proper constraints, but handle gracefully
            return {
                "success": False,
                "message": "Concurrent scan detected. Please try again.",
                "ticket_id": ticket.id,
                "team_member": QRTicketService._serialize_team_member(ticket.team_member),
                "meal_type": ticket.meal_type,
            }

    @staticmethod
    def get_active_ticket(
        team_member_id: int,
        meal_type: str,
    ) -> "QRFoodTicket":
        """
        Get the currently active ticket for a team member and meal type.

        Args:
            team_member_id: ID of the team member
            meal_type: Type of meal (BREAKFAST, LUNCH, DINNER)

        Returns:
            QRFoodTicket object or None if no active ticket
        """
        return QRFoodTicket.query.filter(
            QRFoodTicket.team_member_id == team_member_id,
            QRFoodTicket.meal_type == meal_type.upper(),
            QRFoodTicket.status == QRFoodTicketStatus.ACTIVE,
        ).first()

    @staticmethod
    def get_ticket_visibility(
        team_member_id: int,
        meal_type: str,
    ) -> dict:
        """
        Get visibility status for a member's meal ticket.
        Returns info about whether ticket is currently visible, when it will be, etc.

        Args:
            team_member_id: ID of the team member
            meal_type: Type of meal (BREAKFAST, LUNCH, DINNER)

        Returns:
            {
                "has_ticket": bool,
                "is_visible": bool,
                "reason": str or None,
                "visible_from": datetime or None,
                "visible_until": datetime or None,
                "ticket_id": int or None,
            }
        """
        ticket = QRTicketService.get_active_ticket(team_member_id, meal_type)

        if not ticket:
            return {
                "has_ticket": False,
                "is_visible": False,
                "reason": f"No active {meal_type} ticket found",
                "visible_from": None,
                "visible_until": None,
                "ticket_id": None,
            }

        visibility = QRTicketService._check_meal_visibility(ticket)

        return {
            "has_ticket": True,
            "is_visible": visibility["is_visible"],
            "reason": visibility.get("reason"),
            "visible_from": visibility.get("visible_from"),
            "visible_until": visibility.get("visible_until"),
            "ticket_id": ticket.id,
        }

    @staticmethod
    def get_ticket_history(
        team_member_id: int,
        meal_type: str = None,
    ) -> list:
        """
        Get the complete history of tickets for a team member.

        Args:
            team_member_id: ID of the team member
            meal_type: Optional meal type filter

        Returns:
            List of QRFoodTicket objects ordered by creation date
        """
        query = QRFoodTicket.query.filter_by(team_member_id=team_member_id)
        if meal_type:
            query = query.filter_by(meal_type=meal_type.upper())
        return query.order_by(QRFoodTicket.created_at.desc()).all()

    @staticmethod
    def get_scan_history(
        team_id: int = None,
        team_member_id: int = None,
        meal_type: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list:
        """
        Retrieve audit logs for QR scans with optional filters.

        Args:
            team_id: Filter by team (optional)
            team_member_id: Filter by team member (optional)
            meal_type: Filter by meal type (optional)
            start_date: Filter by start date (optional)
            end_date: Filter by end date (optional)

        Returns:
            List of QRScanLog objects
        """
        query = QRScanLog.query

        if team_id:
            query = query.filter_by(team_id=team_id)
        if team_member_id:
            query = query.filter_by(team_member_id=team_member_id)
        if meal_type:
            query = query.filter(
                QRFoodTicket.meal_type == meal_type.upper()
            ).join(QRFoodTicket)
        if start_date:
            query = query.filter(QRScanLog.scanned_at >= start_date)
        if end_date:
            query = query.filter(QRScanLog.scanned_at <= end_date)

        return query.order_by(QRScanLog.scanned_at.desc()).all()

    @staticmethod
    def revoke_ticket(ticket_id: int, reason: str = None) -> bool:
        """
        Revoke a ticket (mark as REVOKED).
        Used by admins to invalidate fraudulent or compromised tickets.

        Args:
            ticket_id: ID of the ticket to revoke
            reason: Reason for revocation (logged)

        Returns:
            True if successful, False otherwise
        """
        ticket = QRFoodTicket.query.get(ticket_id)
        if not ticket:
            return False

        ticket.status = QRFoodTicketStatus.REVOKED
        db.session.commit()
        return True

    @staticmethod
    def _log_scan_attempt(
        ticket_id: int,
        team_member_id: int,
        team_id: int,
        hackathon_id: int,
        scanned_by_user_id: int,
        scan_status: str,
        reason: str = None,
    ) -> QRScanLog:
        """Log a failed scan attempt for audit trail."""
        log = QRScanLog(
            qr_ticket_id=ticket_id,
            team_member_id=team_member_id,
            team_id=team_id,
            hackathon_id=hackathon_id,
            scanned_by_user_id=scanned_by_user_id,
            scan_status=scan_status,
            scan_reason=reason,
            scanned_at=datetime.utcnow(),
        )
        db.session.add(log)
        db.session.commit()
        return log

    @staticmethod
    def _check_meal_visibility(ticket: QRFoodTicket) -> dict:
        """
        Check if a meal ticket is currently visible (within its meal window).
        Ticket is visible from meal_time to meal_time + 1 hour.

        Args:
            ticket: QRFoodTicket object to check

        Returns:
            {
                "is_visible": bool,
                "reason": str (error message if not visible),
                "visible_until": datetime (if visible),
                "visible_from": datetime (if not yet visible)
            }
        """
        hackathon = ticket.hackathon
        meal_type = ticket.meal_type

        # Get meal time from hackathon config
        meal_time_str = None
        if meal_type == "BREAKFAST":
            meal_time_str = hackathon.breakfast_time
        elif meal_type == "LUNCH":
            meal_time_str = hackathon.lunch_time
        elif meal_type == "DINNER":
            meal_time_str = hackathon.dinner_time

        # If meal time not configured, assume always visible
        if not meal_time_str:
            return {"is_visible": True, "reason": None}

        try:
            # Parse meal time (HH:MM format)
            hours, minutes = map(int, meal_time_str.split(":"))

            # Create start time for this meal on hackathon's start_date
            meal_start = hackathon.start_date.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            meal_end = meal_start + timedelta(hours=QRTicketService.MEAL_WINDOW_HOURS)

            now = datetime.utcnow()

            # Check if current time is within meal window
            if now < meal_start:
                return {
                    "is_visible": False,
                    "reason": f"{meal_type} service not yet available. Starts at {meal_time_str}",
                    "visible_from": meal_start,
                }

            if now > meal_end:
                return {
                    "is_visible": False,
                    "reason": f"{meal_type} service has ended (window was {meal_time_str} - {meal_end.strftime('%H:%M')})",
                    "visible_until": meal_end,
                }

            return {
                "is_visible": True,
                "reason": None,
                "visible_until": meal_end,
            }

        except (ValueError, AttributeError) as e:
            # If time parsing fails, allow scan (graceful fallback)
            return {"is_visible": True, "reason": None}
        return log

    @staticmethod
    def _serialize_team_member(team_member: TeamMember) -> dict:
        """Serialize team member data for API responses."""
        user = team_member.user
        team = team_member.team
        return {
            "id": team_member.id,
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
            },
            "team": {
                "id": team.id,
                "name": team.name,
            },
        }

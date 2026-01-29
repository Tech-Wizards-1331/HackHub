"""
QR Food Ticket API Routes
Endpoints for generating, scanning, and managing food ticket QR codes.
"""

from flask import Blueprint, request, jsonify, current_app
from functools import wraps
from app.extensions import db
from app.models import User, UserRole, Team, Hackathon
from app.utils.qr_ticket_service import QRTicketService
from app.utils.qr_code_generator import QRCodeGenerator

qr_bp = Blueprint("qr", __name__, url_prefix="/api/qr")


def require_role(*roles):
    """Decorator to check user role authorization."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            if not user_id:
                return jsonify({"error": "Unauthorized: no user ID"}), 401

            user = User.query.get(int(user_id))
            if not user:
                return jsonify({"error": "User not found"}), 404

            if user.role not in roles:
                return jsonify(
                    {
                        "error": f"Forbidden: requires one of {[r.value for r in roles]}"
                    }
                ), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


@qr_bp.route("/initialize-tickets", methods=["POST"])
@require_role(UserRole.ADMIN, UserRole.FACULTY)
def initialize_tickets():
    """
    Initialize food tickets for a team.
    Called when hackathon transitions to food service phase.

    Request body:
    {
        "team_id": int,
        "meal_types": ["BREAKFAST", "LUNCH", "DINNER"],
        "hackathon_id": int
    }

    Returns:
    {
        "success": bool,
        "message": str,
        "tickets_created": int,
        "tickets": [...]
    }
    """
    data = request.get_json()
    team_id = data.get("team_id")
    meal_types = data.get("meal_types", ["BREAKFAST", "LUNCH", "DINNER"])
    hackathon_id = data.get("hackathon_id")

    if not team_id or not hackathon_id:
        return jsonify({"error": "Missing team_id or hackathon_id"}), 400

    try:
        tickets = QRTicketService.create_initial_tickets(team_id, meal_types, hackathon_id)
        return jsonify(
            {
                "success": True,
                "message": f"Created {len(tickets)} food tickets",
                "tickets_created": len(tickets),
            }
        ), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@qr_bp.route("/generate/<int:ticket_id>", methods=["GET"])
@require_role(UserRole.ADMIN, UserRole.FACULTY, UserRole.PARTICIPANT)
def generate_qr_image(ticket_id):
    """
    Generate a QR code image (PNG) for a specific ticket.
    Returns the image as PNG or base64-encoded data URI.

    Query params:
    - format: 'png' (binary) or 'base64' (JSON) - default 'base64'

    Returns:
    - PNG binary or JSON with base64-encoded image
    """
    from app.models import QRFoodTicket

    ticket = QRFoodTicket.query.get(ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    team_member = ticket.team_member
    user = team_member.user

    fmt = request.args.get("format", "base64").lower()

    if fmt == "png":
        try:
            img_bytes = QRCodeGenerator.generate_qr_image(
                ticket.qr_token,
                ticket.meal_type,
                user.full_name or user.username,
            )
            from flask import send_file
            return send_file(
                io.BytesIO(img_bytes),
                mimetype="image/png",
                as_attachment=False,
                download_name=f"qr_{ticket.id}.png",
            )
        except Exception as e:
            return jsonify({"error": f"Failed to generate QR: {str(e)}"}), 500

    elif fmt == "base64":
        try:
            b64_str = QRCodeGenerator.generate_qr_base64(
                ticket.qr_token,
                ticket.meal_type,
                user.full_name or user.username,
            )
            return jsonify(
                {
                    "success": True,
                    "ticket_id": ticket_id,
                    "qr_base64": b64_str,
                    "meal_type": ticket.meal_type,
                    "member_name": user.full_name or user.username,
                }
            ), 200
        except Exception as e:
            return jsonify({"error": f"Failed to generate QR: {str(e)}"}), 500

    else:
        return jsonify({"error": "Invalid format. Use 'png' or 'base64'"}), 400


@qr_bp.route("/scan", methods=["POST"])
def scan_ticket():
    """
    Scan a QR code ticket.
    Core operation: validate, mark as used, generate new ticket.

    Request body:
    {
        "qr_token": str,
        "scanned_by_user_id": int (optional, for audit)
    }

    Returns:
    {
        "success": bool,
        "message": str,
        "ticket_id": int or null,
        "team_member": {
            "id": int,
            "user": {...},
            "team": {...}
        } or null,
        "meal_type": str or null,
        "new_qr_token": str or null
    }
    """
    data = request.get_json()
    qr_token = data.get("qr_token", "").strip()
    scanned_by_user_id = data.get("scanned_by_user_id")

    if not qr_token:
        return jsonify({"error": "Missing qr_token"}), 400

    result = QRTicketService.scan_ticket(qr_token, scanned_by_user_id)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@qr_bp.route("/active/<int:team_member_id>/<meal_type>", methods=["GET"])
@require_role(UserRole.ADMIN, UserRole.FACULTY, UserRole.PARTICIPANT)
def get_active_ticket(team_member_id, meal_type):
    """
    Get the currently active QR ticket for a team member and meal type.
    Includes visibility information (whether ticket can currently be scanned).

    Returns:
    {
        "success": bool,
        "ticket": {
            "id": int,
            "qr_token": str,
            "meal_type": str,
            "status": str,
            "created_at": str,
            "expires_at": str or null
        } or null,
        "qr_base64": str or null,
        "visibility": {
            "is_visible": bool,
            "reason": str or null,
            "visible_from": str (ISO format) or null,
            "visible_until": str (ISO format) or null,
            "message": str
        }
    }
    """
    from app.models import QRFoodTicket

    ticket = QRTicketService.get_active_ticket(team_member_id, meal_type)
    visibility = QRTicketService.get_ticket_visibility(team_member_id, meal_type)
    
    if not ticket:
        return jsonify(
            {
                "success": False,
                "message": "No active ticket found",
                "ticket": None,
                "qr_base64": None,
                "visibility": visibility,
            }
        ), 404

    try:
        team_member = ticket.team_member
        user = team_member.user
        
        # Only generate QR image if ticket is currently visible
        qr_b64 = None
        if visibility["is_visible"]:
            qr_b64 = QRCodeGenerator.generate_qr_base64(
                ticket.qr_token, ticket.meal_type, user.full_name or user.username
            )

        return jsonify(
            {
                "success": True,
                "ticket": {
                    "id": ticket.id,
                    "qr_token": ticket.qr_token if visibility["is_visible"] else None,
                    "meal_type": ticket.meal_type,
                    "status": ticket.status.value,
                    "created_at": ticket.created_at.isoformat(),
                    "expires_at": ticket.expires_at.isoformat()
                    if ticket.expires_at
                    else None,
                },
                "qr_base64": qr_b64,
                "visibility": {
                    "is_visible": visibility["is_visible"],
                    "reason": visibility.get("reason"),
                    "visible_from": visibility["visible_from"].isoformat() if visibility.get("visible_from") else None,
                    "visible_until": visibility["visible_until"].isoformat() if visibility.get("visible_until") else None,
                    "message": "Ticket is visible" if visibility["is_visible"] else visibility.get("reason", "Not visible"),
                },
            }
        ), 200
    except Exception as e:
        return jsonify({"error": f"Failed to retrieve ticket: {str(e)}"}), 500


@qr_bp.route("/visibility/<int:team_member_id>/<meal_type>", methods=["GET"])
@require_role(UserRole.ADMIN, UserRole.FACULTY, UserRole.PARTICIPANT)
def check_visibility(team_member_id, meal_type):
    """
    Check if a meal ticket is currently visible (within meal service window).
    Does NOT return the actual QR token (safe for public endpoints).

    Returns:
    {
        "success": bool,
        "team_member_id": int,
        "meal_type": str,
        "has_ticket": bool,
        "is_visible": bool,
        "visible_from": str (ISO format) or null,
        "visible_until": str (ISO format) or null,
        "message": str
    }
    """
    visibility = QRTicketService.get_ticket_visibility(team_member_id, meal_type)
    
    return jsonify(
        {
            "success": True,
            "team_member_id": team_member_id,
            "meal_type": meal_type,
            "has_ticket": visibility["has_ticket"],
            "is_visible": visibility["is_visible"],
            "visible_from": visibility["visible_from"].isoformat() if visibility.get("visible_from") else None,
            "visible_until": visibility["visible_until"].isoformat() if visibility.get("visible_until") else None,
            "message": visibility.get("reason", "Ticket visible") if visibility["is_visible"] else "Ticket not currently visible",
        }
    ), 200


@qr_bp.route("/history/<int:team_member_id>", methods=["GET"])
@require_role(UserRole.ADMIN, UserRole.FACULTY, UserRole.PARTICIPANT)
def get_ticket_history(team_member_id):
    """
    Get ticket history for a team member.

    Query params:
    - meal_type: Filter by meal type (optional)
    - limit: Number of records to return (default 50)
    - offset: Pagination offset (default 0)

    Returns:
    {
        "success": bool,
        "total": int,
        "tickets": [...]
    }
    """
    meal_type = request.args.get("meal_type")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    tickets = QRTicketService.get_ticket_history(team_member_id, meal_type)

    # Apply pagination
    total = len(tickets)
    paginated = tickets[offset : offset + limit]

    return jsonify(
        {
            "success": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "tickets": [
                {
                    "id": t.id,
                    "meal_type": t.meal_type,
                    "status": t.status.value,
                    "created_at": t.created_at.isoformat(),
                    "scanned_at": t.scanned_at.isoformat() if t.scanned_at else None,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                }
                for t in paginated
            ],
        }
    ), 200


@qr_bp.route("/scan-logs", methods=["GET"])
@require_role(UserRole.ADMIN, UserRole.FACULTY)
def get_scan_logs():
    """
    Retrieve scan audit logs (admin only).

    Query params:
    - team_id: Filter by team (optional)
    - team_member_id: Filter by team member (optional)
    - meal_type: Filter by meal type (optional)
    - start_date: ISO format (optional)
    - end_date: ISO format (optional)
    - limit: Number of records (default 100)
    - offset: Pagination offset (default 0)

    Returns:
    {
        "success": bool,
        "total": int,
        "logs": [...]
    }
    """
    from datetime import datetime

    team_id = request.args.get("team_id", type=int)
    team_member_id = request.args.get("team_member_id", type=int)
    meal_type = request.args.get("meal_type")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    start_date = None
    end_date = None

    try:
        if start_date_str:
            start_date = datetime.fromisoformat(start_date_str)
        if end_date_str:
            end_date = datetime.fromisoformat(end_date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use ISO 8601."}), 400

    logs = QRTicketService.get_scan_history(
        team_id=team_id,
        team_member_id=team_member_id,
        meal_type=meal_type,
        start_date=start_date,
        end_date=end_date,
    )

    total = len(logs)
    paginated = logs[offset : offset + limit]

    return jsonify(
        {
            "success": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "logs": [
                {
                    "id": l.id,
                    "ticket_id": l.qr_ticket_id,
                    "team_member_id": l.team_member_id,
                    "team_id": l.team_id,
                    "scan_status": l.scan_status,
                    "scan_reason": l.scan_reason,
                    "scanned_by_user_id": l.scanned_by_user_id,
                    "scanned_at": l.scanned_at.isoformat(),
                }
                for l in paginated
            ],
        }
    ), 200


@qr_bp.route("/revoke/<int:ticket_id>", methods=["POST"])
@require_role(UserRole.ADMIN)
def revoke_ticket(ticket_id):
    """
    Revoke a ticket (mark as REVOKED).
    Admin operation for fraud/compromise scenarios.

    Request body:
    {
        "reason": str (optional)
    }

    Returns:
    {
        "success": bool,
        "message": str
    }
    """
    data = request.get_json() or {}
    reason = data.get("reason")

    if QRTicketService.revoke_ticket(ticket_id, reason):
        return jsonify({"success": True, "message": "Ticket revoked"}), 200
    else:
        return jsonify({"success": False, "message": "Ticket not found"}), 404


import io

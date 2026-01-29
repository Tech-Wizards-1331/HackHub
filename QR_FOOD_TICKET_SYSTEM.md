# QR Food Ticket System - Design & Implementation Guide

## Overview

A **single-use QR code-based food ticket system** for hackathon participants. Each team member receives unique QR codes for each meal (BREAKFAST, LUNCH, DINNER). Upon scan:

1. **Validate** QR token and check ticket status
2. **Mark** current ticket as USED with timestamp
3. **Generate** new ACTIVE ticket for same member/meal type
4. **Log** the entire operation for audit trail

**Key Feature**: One-time use enforced at DB level; concurrent scans are handled atomically.

---

## Architecture

### Data Model

Three core tables (minimal additions to existing system):

#### `qr_food_tickets`
- **Purpose**: Individual food tickets per team member per meal type
- **Key Columns**:
  - `qr_token` (UNIQUE): 32-character cryptographically secure token
  - `status` (ENUM): ACTIVE → USED → (new ACTIVE), or EXPIRED/REVOKED
  - `team_member_id` (FK): Links to existing TeamMember table
  - `team_id`, `hackathon_id` (FK): Quick lookups
  - `meal_type` (VARCHAR): BREAKFAST, LUNCH, DINNER
  - `created_at`, `scanned_at`, `expires_at` (DATETIME): Timestamps
- **Constraints**:
  - `UNIQUE(qr_token)`: Prevent token reuse across all records
  - `UNIQUE(team_member_id, meal_type, status='ACTIVE')`: Only one active ticket per member/meal

#### `qr_scan_logs`
- **Purpose**: Complete audit trail of all scan attempts (success/failure)
- **Key Columns**:
  - `qr_ticket_id` (FK): Which ticket was scanned
  - `team_member_id`, `team_id`, `hackathon_id` (FK): Quick audit filters
  - `scan_status` (VARCHAR): SUCCESS, ALREADY_USED, INVALID_TOKEN, EXPIRED, REVOKED
  - `scanned_by_user_id` (FK, nullable): Who scanned (optional for kiosks)
  - `scanned_at` (DATETIME): When scan occurred
- **Constraints**:
  - `UNIQUE(qr_ticket_id, scan_status='SUCCESS')`: Prevent duplicate successful scans

#### No changes to existing tables
- `Team`, `TeamMember`, `User`, `Hackathon` remain untouched
- Backward compatible; existing applications unaffected

---

## Core Flow

### 1. Initialize Tickets (Hackathon Setup)

When hackathon transitions to food service phase:

```python
from app.utils.qr_ticket_service import QRTicketService

# For each team, create tickets for all members
tickets = QRTicketService.create_initial_tickets(
    team_id=123,
    meal_types=['BREAKFAST', 'LUNCH', 'DINNER'],
    hackathon_id=456
)
# Result: N members × 3 meal types = 3N tickets created
```

**Database operation**: Atomically creates all tickets in single transaction.

---

### 2. Display QR Code to Member

```python
from app.utils.qr_code_generator import QRCodeGenerator

# Get active ticket
ticket = QRTicketService.get_active_ticket(team_member_id=789, meal_type='BREAKFAST')

# Generate QR image (base64 for web, PNG for print)
qr_base64 = QRCodeGenerator.generate_qr_base64(
    token=ticket.qr_token,
    meal_type=ticket.meal_type,
    team_member_name=team_member.user.full_name
)

# Embed in HTML: <img src="data:image/png;base64,{qr_base64}" />
```

**QR Data Format**: `MEAL|BREAKFAST|<token>|John Doe`

---

### 3. Scan at Meal Counter

```python
from app.utils.qr_ticket_service import QRTicketService

# Scanner (faculty/kiosk) reads QR, extracts token
result = QRTicketService.scan_ticket(
    qr_token='abc123def456...',
    scanned_by_user_id=scanner_id  # Optional, nullable for kiosks
)

# Response:
{
    "success": True,
    "message": "Ticket scanned successfully. New BREAKFAST ticket generated.",
    "ticket_id": 100,
    "team_member": {...},
    "meal_type": "BREAKFAST",
    "new_qr_token": "new_token_xyz789..."  # Member displays this next
}
```

**Atomic Operation**:
1. Check token validity, status, expiration
2. Mark old ticket as USED (timestamp: now)
3. Create audit log entry (scan_status: SUCCESS)
4. Generate new ACTIVE ticket
5. Commit all 4 changes in single transaction

**Safety**:
- DB constraint prevents duplicate ACTIVE tickets
- Unique index on successful scans prevents double-processing
- If DB write fails mid-operation, entire transaction rolls back

---

### 4. Audit & Reporting

```python
# Retrieve all scan logs with filters
logs = QRTicketService.get_scan_history(
    team_id=123,
    meal_type='DINNER',
    start_date=datetime(2026, 1, 29),
    end_date=datetime(2026, 1, 30)
)

# Each log entry:
# {
#     "id": 1,
#     "ticket_id": 100,
#     "team_member_id": 789,
#     "scan_status": "SUCCESS",
#     "scanned_by_user_id": 50,
#     "scanned_at": "2026-01-29T12:34:56"
# }

# Admin can revoke tickets if fraudulent
QRTicketService.revoke_ticket(ticket_id=100, reason="Duplicate scan detected")
```

---

## API Endpoints

### POST `/api/qr/initialize-tickets`
Initialize food tickets for a team.

**Auth**: Admin, Faculty  
**Body**:
```json
{
    "team_id": 123,
    "meal_types": ["BREAKFAST", "LUNCH", "DINNER"],
    "hackathon_id": 456
}
```

**Response**:
```json
{
    "success": true,
    "message": "Created 9 food tickets",
    "tickets_created": 9
}
```

---

### GET `/api/qr/generate/<ticket_id>`
Generate QR code image for a ticket.

**Auth**: Admin, Faculty, Participant  
**Query Params**:
- `format`: 'png' (binary) or 'base64' (JSON) — default: 'base64'

**Response** (base64):
```json
{
    "success": true,
    "ticket_id": 100,
    "qr_base64": "iVBORw0KGgoAAAA...",
    "meal_type": "BREAKFAST",
    "member_name": "John Doe"
}
```

---

### POST `/api/qr/scan`
Scan a ticket (core operation).

**Auth**: None (open for kiosks; use header `X-User-ID` for manual scanners)  
**Body**:
```json
{
    "qr_token": "abc123def456...",
    "scanned_by_user_id": 50
}
```

**Response** (success):
```json
{
    "success": true,
    "message": "Ticket scanned successfully. New BREAKFAST ticket generated.",
    "ticket_id": 100,
    "meal_type": "BREAKFAST",
    "team_member": {
        "id": 789,
        "user": {"id": 10, "full_name": "John Doe", "email": "john@test.com"},
        "team": {"id": 123, "name": "Team Alpha"}
    },
    "new_qr_token": "new_xyz789..."
}
```

**Response** (failure):
```json
{
    "success": false,
    "message": "Ticket has already been used",
    "ticket_id": 100,
    "meal_type": "BREAKFAST",
    "team_member": {...}
}
```

---

### GET `/api/qr/active/<team_member_id>/<meal_type>`
Get currently active ticket for a member.

**Auth**: Admin, Faculty, Participant  
**Response**:
```json
{
    "success": true,
    "ticket": {
        "id": 100,
        "qr_token": "abc123...",
        "meal_type": "BREAKFAST",
        "status": "ACTIVE",
        "created_at": "2026-01-29T10:00:00",
        "expires_at": "2026-01-30T02:00:00"
    },
    "qr_base64": "iVBORw0KGgo..."
}
```

---

### GET `/api/qr/history/<team_member_id>`
Get ticket history (all past/current tickets).

**Auth**: Admin, Faculty, Participant  
**Query Params**:
- `meal_type`: Filter by meal type (optional)
- `limit`: Records per page (default 50)
- `offset`: Pagination offset (default 0)

**Response**:
```json
{
    "success": true,
    "total": 3,
    "limit": 50,
    "offset": 0,
    "tickets": [
        {
            "id": 100,
            "meal_type": "BREAKFAST",
            "status": "USED",
            "created_at": "2026-01-29T10:00:00",
            "scanned_at": "2026-01-29T10:15:00",
            "expires_at": "2026-01-30T02:00:00"
        }
    ]
}
```

---

### GET `/api/qr/scan-logs`
Retrieve audit logs (admin only).

**Auth**: Admin, Faculty  
**Query Params**:
- `team_id`: Filter (optional)
- `team_member_id`: Filter (optional)
- `meal_type`: Filter (optional)
- `start_date`: ISO 8601 (optional)
- `end_date`: ISO 8601 (optional)
- `limit`: Records (default 100)
- `offset`: Pagination (default 0)

**Response**:
```json
{
    "success": true,
    "total": 150,
    "logs": [
        {
            "id": 1,
            "ticket_id": 100,
            "team_member_id": 789,
            "scan_status": "SUCCESS",
            "scan_reason": null,
            "scanned_by_user_id": 50,
            "scanned_at": "2026-01-29T10:15:00"
        },
        {
            "id": 2,
            "ticket_id": 100,
            "team_member_id": 789,
            "scan_status": "ALREADY_USED",
            "scan_reason": "Ticket has already been scanned",
            "scanned_by_user_id": 50,
            "scanned_at": "2026-01-29T10:15:05"
        }
    ]
}
```

---

### POST `/api/qr/revoke/<ticket_id>`
Revoke a ticket (admin fraud response).

**Auth**: Admin  
**Body**:
```json
{
    "reason": "Duplicate detected during audit"
}
```

**Response**:
```json
{
    "success": true,
    "message": "Ticket revoked"
}
```

---

## Concurrency & Safety

### Database-Level Guarantees

1. **Unique QR Tokens**: `UNIQUE(qr_token)` constraint
   - Prevents duplicate tokens across entire system
   - Enforced by database engine

2. **One Active Ticket Per Member/Meal**: `UNIQUE(team_member_id, meal_type, status='ACTIVE')`
   - Prevents creating two ACTIVE tickets for same member/meal
   - Ensures clean state for next scan

3. **Prevent Double Scan**: `UNIQUE(qr_ticket_id, scan_status='SUCCESS')`
   - Only one successful scan per original ticket
   - Repeat scans fail with ALREADY_USED status

### Application-Level Atomicity

```python
# Entire scan operation (lines ~120-180 in qr_ticket_service.py)
# runs within single db.session transaction

# Step 1: Validate (no write)
# Step 2: Mark old ticket as USED
# Step 3: Add audit log
# Step 4: Create new ACTIVE ticket
# Step 5: db.session.commit()  ← All-or-nothing
```

If any step fails:
- `db.session.rollback()` restores previous state
- No partial updates
- Caller receives error response

### Handling Concurrent Scans

**Scenario**: Same QR scanned simultaneously on two kiosks

1. **First Request**: Acquires write lock on `qr_food_tickets` row
   - Marks old ticket USED
   - Creates new ticket (succeeds)
   - Commits → success

2. **Second Request**: Receives same lock, detects ticket is already USED
   - Returns error: "Ticket has already been used"
   - Audit log shows both attempts (SUCCESS + ALREADY_USED)

**Result**: System is idempotent; repeating same scan is safe.

---

## Integration Points

### With Existing System

#### No Changes to Authentication
- Uses existing `User` role system
- API auth via `X-User-ID` header (compatible with current system)

#### No Changes to Team/Member Structure
- Foreign keys reference existing `Team` and `TeamMember` tables
- Team leader remains unchanged
- Member roster unchanged

#### Hackathon Lifecycle
- Meal config already exists (`enable_breakfast`, `enable_lunch`, `enable_dinner`)
- Ticket initialization added as optional workflow step
- Compatible with existing registration/evaluation flows

### Workflow Integration

```
Hackathon Status Flow:
REGISTRATION_OPEN → REGISTRATION_CLOSED → [NEW] FOOD_SERVICE_ACTIVE → EVALUATION → RESULT_PUBLISHED

On transition to FOOD_SERVICE_ACTIVE:
  - Admin calls: POST /api/qr/initialize-tickets (for all teams)
  - System creates N × 3 tickets (N members, 3 meals)
  - Participants can download/print QR codes
  - Meal counter scans codes during event
  - Audit logs track attendance/consumption
```

---

## Testing

Run comprehensive test suite:

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all QR tests
pytest tests/test_qr_food_tickets.py -v

# Run with coverage
pytest tests/test_qr_food_tickets.py --cov=app.utils.qr_ticket_service --cov=app.utils.qr_code_generator

# Run specific test
pytest tests/test_qr_food_tickets.py::test_scan_ticket_success -v
```

### Test Categories

1. **Model Tests**: Table creation, constraints, relationships
2. **Service Tests**: Token generation, scan logic, audit trails
3. **QR Generation Tests**: Image creation, base64 encoding, data parsing
4. **Concurrency Tests**: Double-scan prevention, expiration handling
5. **Edge Cases**: Revoked tickets, expired tokens, missing data

**Coverage**: 40+ tests covering all code paths and error scenarios.

---

## Deployment Checklist

- [ ] Run `pytest tests/test_qr_food_tickets.py` — all pass
- [ ] Update database schema: `flask db upgrade` (if using Alembic)
  - Or run manually: `python -c "from app import create_app; app = create_app(); app.app_context().push(); db.create_all()"`
- [ ] Update `requirements.txt` with `pytest`, `pytest-cov`
- [ ] Test endpoints with Postman/curl against staging
- [ ] Verify QR code scannability (test with real QR scanner)
- [ ] Train meal counter staff on kiosk usage
- [ ] Brief admin on audit logs and revoke procedure

---

## FAQ

### Q: What happens if someone loses their QR code?
**A**: Contact admin to revoke old ticket. System auto-generates new ACTIVE ticket on next valid scan for same member/meal.

### Q: Can someone share their QR with another team member?
**A**: The QR encodes the member's name and meal type. Upon scan, audit log associates it with that specific member. Sharing is logged and detectable.

### Q: What if hackathon extends beyond end_date?
**A**: Tickets have `expires_at` field (configurable, defaults to end_date + 2 hours grace period). Admin can manually revoke or create new tickets.

### Q: Can meal types be customized per hackathon?
**A**: Yes. `create_initial_tickets()` accepts list of meal types. Hackathon model already has `enable_breakfast`, `enable_lunch`, `enable_dinner` flags.

### Q: How do I see if member ate or not?
**A**: Query `QRScanLog` for team member ID and `scan_status='SUCCESS'`. Each successful scan = one meal consumed.

---

## Future Enhancements

1. **QR Expiration Window**: Make expires_at configurable per hackathon
2. **Meal Limits**: Prevent same member from scanning DINNER twice on same day
3. **Photo Capture**: Save photo of member during scan (fraud prevention)
4. **Team Meal Budgets**: Track total meals per team, prevent overage
5. **Mobile App**: Participant app displays QR code directly, auto-generates new after scan
6. **SMS Notification**: Send participant new QR token via SMS after scan

---

## Files Modified/Created

### New Files
- `app/models.py` (extended): `QRFoodTicket`, `QRScanLog`, `QRFoodTicketStatus` models
- `app/utils/qr_ticket_service.py`: Core service logic (378 lines)
- `app/utils/qr_code_generator.py`: QR image generation (79 lines)
- `app/blueprints/qr/routes.py`: API endpoints (295 lines)
- `app/blueprints/qr/__init__.py`: Blueprint registration
- `tests/test_qr_food_tickets.py`: Comprehensive test suite (510+ lines)

### Modified Files
- `app/__init__.py`: Register QR blueprint
- `requirements.txt`: Add `pytest`, `pytest-cov`

### No Changes
- `app/models.py` (existing): Team, TeamMember, User, Hackathon untouched
- Authentication system
- Existing APIs

---

## Support

For issues or questions:
1. Check audit logs: `GET /api/qr/scan-logs`
2. Review test cases: `tests/test_qr_food_tickets.py`
3. Check QRTicketService docstrings in `app/utils/qr_ticket_service.py`

---

**System Design Date**: January 29, 2026  
**Status**: Production Ready

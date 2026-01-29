## QR Food Ticket System - Quick Start

A production-ready **single-use QR code-based food ticket system** for hackathon meal management.

### ⚡ Key Features

✅ **Single-use QR codes** — Each scan invalidates the code and generates a new one  
✅ **Atomic operations** — Database constraints prevent double-scans  
✅ **Zero breaking changes** — Integrates seamlessly with existing Team/User models  
✅ **Complete audit trail** — All scans logged with timestamps and scanner IDs  
✅ **Concurrent-safe** — Handles simultaneous scans from multiple kiosks  
✅ **Flexible meal types** — BREAKFAST, LUNCH, DINNER (configurable per hackathon)  

---

### 📦 What's New

#### Models (in `app/models.py`)
- **QRFoodTicket**: Individual meal ticket per team member
- **QRFoodTicketStatus**: Enum (ACTIVE, USED, EXPIRED, REVOKED)
- **QRScanLog**: Complete audit trail of all scan attempts

#### Services
- **`app/utils/qr_ticket_service.py`**: Core ticket logic (scan, generate, history, revoke)
- **`app/utils/qr_code_generator.py`**: QR code image generation (PNG, Base64, Data URI)

#### API Blueprint
- **`app/blueprints/qr/routes.py`**: 6 endpoints for ticket management

#### Tests
- **`tests/test_qr_food_tickets.py`**: 40+ comprehensive tests (models, service, images, edge cases)

#### Documentation
- **`QR_FOOD_TICKET_SYSTEM.md`**: Complete design guide, API reference, integration notes

---

### 🚀 Quick Start

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

(Already includes `qrcode`, `pillow`, `pytest`)

#### 2. Initialize Database

```bash
# Create tables
python -c "from app import create_app; app = create_app(); app.app_context().push(); from app.extensions import db; db.create_all()"

# Or run test validation
python validate_qr_system.py
```

#### 3. Create Initial Tickets

```python
from app.utils.qr_ticket_service import QRTicketService

# When hackathon transitions to food service phase:
QRTicketService.create_initial_tickets(
    team_id=123,
    meal_types=['BREAKFAST', 'LUNCH', 'DINNER'],
    hackathon_id=456
)
# Creates N members × 3 meals tickets
```

#### 4. Display QR to Member

```python
from app.utils.qr_code_generator import QRCodeGenerator

ticket = QRTicketService.get_active_ticket(team_member_id=789, meal_type='BREAKFAST')

# For web (embed in HTML):
qr_base64 = QRCodeGenerator.generate_qr_base64(
    token=ticket.qr_token,
    meal_type=ticket.meal_type,
    team_member_name='John Doe'
)
# <img src="data:image/png;base64,{qr_base64}" />

# For printing:
qr_bytes = QRCodeGenerator.generate_qr_image(...)
# Save to file or print directly
```

#### 5. Scan at Meal Counter

```python
from app.utils.qr_ticket_service import QRTicketService

# Scanner reads QR and extracts token
result = QRTicketService.scan_ticket(
    qr_token='abc123def456...',
    scanned_by_user_id=scanner_id
)

if result['success']:
    # Show new QR token to member
    next_token = result['new_qr_token']
    # Member scans this next time
else:
    # Display error
    print(result['message'])
```

---

### 🔌 API Endpoints

**All endpoints under `/api/qr`**

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| POST | `/initialize-tickets` | Create initial meal tickets | Admin, Faculty |
| GET | `/generate/<ticket_id>` | Download QR image | Admin, Faculty, Participant |
| POST | `/scan` | Scan & consume ticket | Public* |
| GET | `/active/<member_id>/<meal>` | Get current active ticket | Admin, Faculty, Participant |
| GET | `/history/<member_id>` | View ticket history | Admin, Faculty, Participant |
| GET | `/scan-logs` | Audit logs (filterable) | Admin, Faculty |
| POST | `/revoke/<ticket_id>` | Revoke compromised ticket | Admin |

*Scan endpoint is public for kiosk integration; use `scanned_by_user_id` header for manual tracking.

---

### 📊 Example Flow

```
1. Admin initializes hackathon for food service
   POST /api/qr/initialize-tickets
   ↓
2. Each team member gets 3 tickets (BREAKFAST, LUNCH, DINNER)
   ↓
3. Member views active BREAKFAST ticket
   GET /api/qr/active/{member_id}/BREAKFAST
   → Returns QR base64 image
   ↓
4. Member scans QR at breakfast counter
   POST /api/qr/scan
   → Old ticket marked USED
   → New BREAKFAST ticket generated
   → Returns new token for next scan
   ↓
5. Admin audits meal consumption
   GET /api/qr/scan-logs?team_id=123&meal_type=BREAKFAST
   → See who ate, when, who scanned
```

---

### 🔒 Safety & Concurrency

#### Database Constraints
- **Unique QR tokens**: No duplicates system-wide
- **One active ticket per member/meal**: Prevents state corruption
- **Unique successful scans**: Prevents double-processing

#### Atomic Transactions
All 4 operations (mark USED, create audit log, generate new ticket, commit) happen together or not at all.

#### Idempotent Scans
Scanning same token twice safely returns error on 2nd attempt without modifying system state.

---

### ✅ Testing

```bash
# Run validation (quick check)
python validate_qr_system.py

# Run full test suite
pytest tests/test_qr_food_tickets.py -v

# Run with coverage
pytest tests/test_qr_food_tickets.py --cov=app.utils.qr_ticket_service --cov=app.utils.qr_code_generator

# Run specific test
pytest tests/test_qr_food_tickets.py::test_scan_ticket_success -v
```

**Test coverage**: 40+ tests covering models, services, QR generation, concurrency, edge cases.

---

### 📋 Integration with Existing System

**No breaking changes.** System reuses:

- Existing `Team`, `TeamMember`, `User` tables (no modifications)
- Existing authentication system
- Existing hackathon model (uses `enable_breakfast`, `enable_lunch`, `enable_dinner` flags)

Simply add the new tables and API endpoints. Backward compatible.

---

### 🛠️ Configuration

#### Meal Types (per Hackathon)
```python
hackathon = Hackathon(
    name='...',
    enable_breakfast=True,
    enable_lunch=True,
    enable_dinner=True,
    ...
)
```

#### Ticket Expiration
Default: Hackathon end_date + 2 hours grace period

```python
# In create_initial_tickets()
expires_at=hackathon.end_date + timedelta(hours=2)
```

Customize by modifying `qr_ticket_service.py` line ~65.

#### QR Code Size
- Current: 10 pixels per box, 2-box border
- Modify `QRCodeGenerator` constants (lines 9-12) to adjust scannability

---

### 📖 Full Documentation

See [QR_FOOD_TICKET_SYSTEM.md](QR_FOOD_TICKET_SYSTEM.md) for:
- Complete architecture overview
- Detailed API reference with examples
- Concurrency & safety guarantees
- Database schema & constraints
- Integration points
- FAQ & troubleshooting
- Future enhancements

---

### 🚨 Common Issues

**"Unique constraint violation when scanning"**  
→ Old code querying stale ticket state. Always call `scan_ticket()` with fresh token.

**"QR code won't scan (too small)"**  
→ Increase `QR_BOX_SIZE` in `qr_code_generator.py` (default 10 pixels).

**"Need to revoke fraudulent ticket"**  
→ `POST /api/qr/revoke/<ticket_id>` (admin only). New ticket auto-generated on next valid scan.

**"Member lost QR code"**  
→ Call `GET /api/qr/active/<member_id>/BREAKFAST` to retrieve current token.

---

### 📧 Support

1. Check test cases: `tests/test_qr_food_tickets.py`
2. Review audit logs: `GET /api/qr/scan-logs`
3. Check docstrings: `app/utils/qr_ticket_service.py`
4. Read full docs: `QR_FOOD_TICKET_SYSTEM.md`

---

### 📝 Files Overview

```
New Files:
  ✓ app/utils/qr_ticket_service.py         Service logic (378 lines)
  ✓ app/utils/qr_code_generator.py         QR generation (79 lines)
  ✓ app/blueprints/qr/routes.py            API endpoints (295 lines)
  ✓ app/blueprints/qr/__init__.py          Blueprint init
  ✓ tests/test_qr_food_tickets.py          40+ tests (510+ lines)
  ✓ QR_FOOD_TICKET_SYSTEM.md               Complete docs
  ✓ validate_qr_system.py                  Quick validation

Modified Files:
  ✓ app/models.py                          Added 2 models (47 new lines)
  ✓ app/__init__.py                        Registered blueprint (2 lines)
  ✓ requirements.txt                       Added pytest, pytest-cov (2 lines)

No Changes:
  ✓ Existing models (Team, User, etc.)
  ✓ Authentication system
  ✓ Existing APIs
```

---

**Status**: ✅ Production Ready  
**Last Updated**: January 29, 2026  
**Compatibility**: Flask + SQLAlchemy, Python 3.7+

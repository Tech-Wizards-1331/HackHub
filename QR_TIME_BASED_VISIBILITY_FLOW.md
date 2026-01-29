# QR Food Ticket System - Time-Based Visibility Flow

Complete end-to-end flow with time-based meal availability.

---

## Complete System Flow

### Phase 1: Hackathon Setup (Admin)

```
1. Admin creates Hackathon
   - Navigate to: /admin/create_hackathon
   - Fill in: name, description, start_date, max_teams, etc.
   - Enable Meals: [✓] Breakfast [✓] Lunch [✓] Dinner
   - Set Meal Times:
     • Breakfast: 07:00 (visible 07:00 - 08:00)
     • Lunch:     12:30 (visible 12:30 - 13:30)
     • Dinner:    18:00 (visible 18:00 - 19:00)
   - Click: Create Hackathon
   
   → Hackathon stored with meal config
```

### Phase 2: Team Registration (Participant)

```
2. Participants register for hackathon
   - Team leader creates team
   - Invites/adds team members
   - Status: Registration complete
   
   → Teams with members created
```

### Phase 3: Initialize Meal Tickets (Admin)

```
3. Admin transitions hackathon to Food Service phase
   OR
   Admin manually initializes tickets via API:
   
   POST /api/qr/initialize-tickets
   {
     "team_id": 123,
     "meal_types": ["BREAKFAST", "LUNCH", "DINNER"],
     "hackathon_id": 456
   }
   
   Response:
   {
     "success": true,
     "message": "Created 9 food tickets",
     "tickets_created": 9  // 3 members × 3 meals
   }
   
   → For each team member:
     • 1 BREAKFAST ticket (ACTIVE status)
     • 1 LUNCH ticket (ACTIVE status)
     • 1 DINNER ticket (ACTIVE status)
```

### Phase 4: Member Checks Meal Availability (Participant)

**Before Breakfast (e.g., 06:30):**

```
Participant calls:
GET /api/qr/visibility/team_member_id/BREAKFAST

Response:
{
  "success": true,
  "team_member_id": 100,
  "meal_type": "BREAKFAST",
  "has_ticket": true,
  "is_visible": false,
  "visible_from": "2026-01-29T07:00:00",
  "visible_until": "2026-01-29T08:00:00",
  "message": "BREAKFAST service not yet available. Starts at 07:00"
}

→ Member sees: "Breakfast available at 07:00"
→ No QR code displayed yet
```

**At Breakfast Time (e.g., 07:15):**

```
Participant calls:
GET /api/qr/active/team_member_id/BREAKFAST

Response:
{
  "success": true,
  "ticket": {
    "id": 1,
    "qr_token": "abc123def456...",
    "meal_type": "BREAKFAST",
    "status": "ACTIVE",
    "created_at": "2026-01-29T06:00:00",
    "expires_at": "2026-01-30T02:00:00"
  },
  "qr_base64": "iVBORw0KGgoAAAA...",
  "visibility": {
    "is_visible": true,
    "reason": null,
    "visible_from": "2026-01-29T07:00:00",
    "visible_until": "2026-01-29T08:00:00",
    "message": "Ticket is visible"
  }
}

→ Member sees: QR code displayed
→ Ready to scan
```

**After Breakfast Window (e.g., 08:15):**

```
Participant calls:
GET /api/qr/active/team_member_id/BREAKFAST

Response:
{
  "success": true,
  "ticket": {
    "id": 1,
    "qr_token": null,  // Hidden
    "meal_type": "BREAKFAST",
    "status": "ACTIVE",
    ...
  },
  "qr_base64": null,  // No image
  "visibility": {
    "is_visible": false,
    "visible_until": "2026-01-29T08:00:00",
    "message": "BREAKFAST service has ended (window was 07:00 - 08:00)"
  }
}

→ Member sees: "Breakfast service has ended"
→ QR code removed from display
```

### Phase 5: Member Scans During Meal Window

**Breakfast Time (07:00 - 08:00):**

```
Participant arrives at breakfast counter at 07:30
Counter staff scans QR code (or participant taps phone):

POST /api/qr/scan
{
  "qr_token": "abc123def456...",
  "scanned_by_user_id": 50  // Optional: staff ID
}

Server checks:
1. ✓ Token valid
2. ✓ Ticket is ACTIVE
3. ✓ Current time is 07:30
4. ✓ Breakfast service window is 07:00 - 08:00
5. ✓ Ticket is visible

Response (Success):
{
  "success": true,
  "message": "Ticket scanned successfully. New BREAKFAST ticket generated.",
  "ticket_id": 1,
  "meal_type": "BREAKFAST",
  "team_member": {
    "id": 100,
    "user": { "full_name": "John Doe", ... },
    "team": { "name": "Alpha Squad", ... }
  },
  "new_qr_token": "new_xyz789..."
}

Changes in Database:
1. Old ticket (id=1) → Status: USED, scanned_at: 2026-01-29T07:30:00
2. New ticket (id=10) created → Status: ACTIVE, qr_token: "new_xyz789..."
3. Audit log created → ticket_id: 1, scan_status: SUCCESS, scanned_at: 07:30

→ Member is allowed to eat
→ Receives new QR for next meal (LUNCH)
→ Old QR is invalidated forever
```

### Phase 6: Member Scans Again (Should Fail)

**If participant tries to scan same token again:**

```
POST /api/qr/scan
{
  "qr_token": "abc123def456...",  // Old token (already USED)
  "scanned_by_user_id": 50
}

Server checks:
1. ✓ Token valid
2. ✗ Ticket status is USED (not ACTIVE)

Response (Error):
{
  "success": false,
  "message": "Ticket has already been used",
  "ticket_id": 1,
  "meal_type": "BREAKFAST",
  "team_member": {...}
}

Database:
- Audit log created → scan_status: ALREADY_USED, scan_reason: "Ticket has already been scanned"

→ Double-scan prevented
→ No new ticket generated
→ Incident logged
```

### Phase 7: Try to Scan After Window Closes

**After Breakfast (e.g., 08:30):**

```
Participant tries to scan new BREAKFAST token:

POST /api/qr/scan
{
  "qr_token": "new_xyz789...",  // New token
  "scanned_by_user_id": 50
}

Server checks:
1. ✓ Token valid
2. ✓ Ticket is ACTIVE
3. ✗ Current time is 08:30
4. ✗ Breakfast service window is 07:00 - 08:00
5. ✗ Ticket is NOT visible (outside window)

Response (Error):
{
  "success": false,
  "message": "BREAKFAST service has ended (window was 07:00 - 08:00)",
  "ticket_id": 10,
  "meal_type": "BREAKFAST",
  "team_member": {...}
}

Database:
- Audit log created → scan_status: NOT_VISIBLE, scan_reason: "Breakfast service has ended..."

→ Scan rejected
→ Member cannot eat
→ Incident logged for admin review
```

### Phase 8: Lunch Time (12:30 - 13:30)

```
Member checks lunch availability at 12:00:

GET /api/qr/visibility/team_member_id/LUNCH

Response:
{
  "is_visible": false,
  "message": "LUNCH service not yet available. Starts at 12:30",
  "visible_from": "2026-01-29T12:30:00"
}

→ Member waits

At 12:35, QR is visible:
GET /api/qr/active/team_member_id/LUNCH

Response:
{
  "success": true,
  "qr_base64": "...",  // Image generated
  "visibility": {
    "is_visible": true,
    "message": "Ticket is visible"
  }
}

Member scans at 12:40:
POST /api/qr/scan
{
  "qr_token": "lunch_token_abc123...",
  "scanned_by_user_id": 51
}

Response (Success):
{
  "success": true,
  "new_qr_token": "new_lunch_token_..."
}

Changes:
1. Old LUNCH ticket → USED
2. New LUNCH ticket → ACTIVE
3. Audit log → SUCCESS at 12:40
```

### Phase 9: Dinner Time (18:00 - 19:00)

Same pattern as breakfast and lunch.

```
Member checks at 17:00 → Not visible
Member checks at 18:05 → Visible, QR displayed
Member scans at 18:30 → Success, new ticket generated
Member tries to scan at 19:30 → Fails (window closed)
```

### Phase 10: Admin Reviews Audit Logs

```
Admin wants to see meal consumption:

GET /api/qr/scan-logs?team_id=123&start_date=2026-01-29T00:00:00&end_date=2026-01-30T00:00:00

Response:
{
  "success": true,
  "total": 5,
  "logs": [
    {
      "id": 1,
      "ticket_id": 1,
      "team_member_id": 100,
      "scan_status": "SUCCESS",
      "scanned_at": "2026-01-29T07:30:00",
      "scanned_by_user_id": 50
    },
    {
      "id": 2,
      "ticket_id": 10,
      "team_member_id": 100,
      "scan_status": "NOT_VISIBLE",
      "scan_reason": "BREAKFAST service has ended...",
      "scanned_at": "2026-01-29T08:30:00",
      "scanned_by_user_id": 50
    },
    {
      "id": 3,
      "ticket_id": 3,
      "team_member_id": 100,
      "scan_status": "SUCCESS",
      "scanned_at": "2026-01-29T12:40:00",
      "scanned_by_user_id": 51
    },
    {
      "id": 4,
      "ticket_id": 5,
      "team_member_id": 100,
      "scan_status": "SUCCESS",
      "scanned_at": "2026-01-29T18:15:00",
      "scanned_by_user_id": 52
    },
    {
      "id": 5,
      "ticket_id": 6,
      "team_member_id": 101,  // Team member 2
      "scan_status": "SUCCESS",
      "scanned_at": "2026-01-29T07:45:00",
      "scanned_by_user_id": 50
    }
  ]
}

→ Admin sees:
  • Member 100 ate breakfast at 07:30 (✓)
  • Member 100 tried to eat after breakfast at 08:30 (✗ outside window)
  • Member 100 ate lunch at 12:40 (✓)
  • Member 100 ate dinner at 18:15 (✓)
  • Member 101 ate breakfast at 07:45 (✓)
```

---

## Key Rules Enforced

### Rule 1: Visibility Window
- Ticket is only visible (QR returned) if current_time is within meal window
- Meal window: meal_start_time to meal_start_time + 1 hour
- Examples:
  - Breakfast 07:00 → visible 07:00-08:00
  - Lunch 12:30 → visible 12:30-13:30
  - Dinner 18:00 → visible 18:00-19:00

### Rule 2: Single-Use (Atomic)
- When scanned successfully:
  1. Old ticket marked USED
  2. Audit log recorded
  3. New ACTIVE ticket created
  4. All in single transaction
- No partial updates possible

### Rule 3: Double-Scan Prevention
- Same token cannot be scanned twice
- Second attempt fails with "already used" error
- Attempted double-scans are logged

### Rule 4: Time-Based Rejection
- Scans outside meal window are rejected
- Error message tells user when service is available/was available
- Attempts logged for audit

### Rule 5: Token Expiration
- Ticket expires at hackathon.end_date + 2 hours
- After expiration, all scans fail
- Prevents old tickets from working after event

---

## Database State Changes

### QRFoodTicket Table
```
Hackathon 456:
  breakfast_time: "07:00"
  lunch_time: "12:30"
  dinner_time: "18:00"

Team 123 members: [Member 100, Member 101, Member 102]

Initial state (after initialize):
id | team_id | member_id | meal_type | status | qr_token      | created_at           | expires_at
---|---------|-----------|-----------|--------|---------------|----------------------|-----------------------
1  | 123     | 100       | BREAKFAST | ACTIVE | abc123...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
2  | 123     | 101       | BREAKFAST | ACTIVE | def456...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
3  | 123     | 102       | BREAKFAST | ACTIVE | ghi789...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
4  | 123     | 100       | LUNCH     | ACTIVE | jkl012...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
5  | 123     | 101       | LUNCH     | ACTIVE | mno345...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
6  | 123     | 102       | LUNCH     | ACTIVE | pqr678...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
7  | 123     | 100       | DINNER    | ACTIVE | stu901...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
8  | 123     | 101       | DINNER    | ACTIVE | vwx234...     | 2026-01-29 06:00:00  | 2026-01-30 02:00:00
9  | 123     | 102       | DINNER    | ACTIVE | yz567...      | 2026-01-29 06:00:00  | 2026-01-30 02:00:00

After breakfast at 07:30 (member 100 scans):
id | team_id | member_id | meal_type | status | scanned_at           | created_at
---|---------|-----------|-----------|--------|----------------------|---------------------
1  | 123     | 100       | BREAKFAST | USED   | 2026-01-29 07:30:00  | 2026-01-29 06:00:00
10 | 123     | 100       | BREAKFAST | ACTIVE | NULL                 | 2026-01-29 07:30:00

(Ticket 1 is USED, Ticket 10 is new ACTIVE for next breakfast)
```

### QRScanLog Table
```
After 07:30 breakfast scan (member 100):
id | ticket_id | member_id | scan_status | scanned_by_user_id | scanned_at              | scan_reason
---|-----------|-----------|-------------|-------------------|-------------------------|----------------------------
1  | 1         | 100       | SUCCESS     | 50                | 2026-01-29 07:30:00     | NULL

After 08:30 attempt (member 100):
id | ticket_id | member_id | scan_status | scanned_by_user_id | scanned_at              | scan_reason
---|-----------|-----------|-------------|-------------------|-------------------------|-----------------------------------------------
2  | 10        | 100       | NOT_VISIBLE | 50                | 2026-01-29 08:30:00     | "BREAKFAST service has ended (window was 07:00 - 08:00)"

After 12:40 lunch scan (member 100):
id | ticket_id | member_id | scan_status | scanned_by_user_id | scanned_at              | scan_reason
---|-----------|-----------|-------------|-------------------|-------------------------|----------------------------
3  | 4         | 100       | SUCCESS     | 51                | 2026-01-29 12:40:00     | NULL
```

---

## API Endpoints Summary

| Method | Endpoint | Purpose | Returns | Auth |
|--------|----------|---------|---------|------|
| POST | `/api/qr/initialize-tickets` | Create meal tickets for team | tickets_created count | Admin, Faculty |
| GET | `/api/qr/visibility/<member_id>/<meal>` | Check if meal ticket is visible | is_visible, visible_from/until | User |
| GET | `/api/qr/active/<member_id>/<meal>` | Get ticket with QR (if visible) | ticket + qr_base64 + visibility | User |
| GET | `/api/qr/generate/<ticket_id>` | Download QR image | PNG or Base64 | User |
| POST | `/api/qr/scan` | Scan a QR code | success, new_qr_token | Public |
| GET | `/api/qr/history/<member_id>` | View ticket history | List of tickets | User |
| GET | `/api/qr/scan-logs` | Audit logs (filtered) | Complete audit trail | Admin |
| POST | `/api/qr/revoke/<ticket_id>` | Revoke ticket (fraud) | success | Admin |

---

## Configuration (Admin UI)

### Create Hackathon Form
```
Name: TechCon 2026
Description: Annual hackathon
Start Date: 2026-01-29 10:00

[✓] Enable Breakfast
  Breakfast Time: 07:00
[✓] Enable Lunch
  Lunch Time: 12:30
[✓] Enable Dinner
  Dinner Time: 18:00

Max Teams: 10
Min Team Size: 2
Max Team Size: 4

[Create Hackathon]
```

### Manage Hackathon Form
```
Current Status: ONGOING
Current Meals:
  [✓] Breakfast at 07:00
  [✓] Lunch at 12:30
  [✓] Dinner at 18:00

[Update Meals]
```

---

## Error Scenarios & Handling

### Scenario 1: Member Arrives Too Early
**Time**: 06:45 (15 min before breakfast)

```
GET /api/qr/active/100/BREAKFAST

Response:
{
  "success": false,
  "ticket": null,
  "qr_base64": null,
  "visibility": {
    "is_visible": false,
    "message": "BREAKFAST service not yet available. Starts at 07:00",
    "visible_from": "2026-01-29T07:00:00"
  }
}

Frontend shows: ⏳ "Breakfast available at 07:00"
```

### Scenario 2: Member Arrives Late
**Time**: 08:30 (30 min after breakfast ends)

```
GET /api/qr/active/100/BREAKFAST

Response:
{
  "success": false,
  "ticket": null,
  "qr_base64": null,
  "visibility": {
    "is_visible": false,
    "message": "BREAKFAST service has ended (window was 07:00 - 08:00)",
    "visible_until": "2026-01-29T08:00:00"
  }
}

Frontend shows: ❌ "Breakfast service ended at 08:00"
```

### Scenario 3: Tries to Scan Old Ticket
**Time**: 07:35 (after already scanned at 07:30)

```
POST /api/qr/scan
{
  "qr_token": "abc123..."  // Old ticket from first scan
}

Response:
{
  "success": false,
  "message": "Ticket has already been used"
}

Database: Audit log created with scan_status: ALREADY_USED
```

### Scenario 4: Admin Updates Meal Times
**Before**: Lunch at 12:30
**After**: Lunch at 13:00

Change is immediate:
- Existing active tickets use new times
- Any pending scans use new window
- Tickets already USED are unaffected
- Upcoming scans see new window

---

## Testing the Flow

### Test 1: Manual Time-Based Test
```bash
# Create hackathon with Breakfast at 07:00
# Initialize tickets
# Try to get QR before 07:00 → Not visible
# Wait until 07:00
# Get QR → Visible
# Scan → Success, new ticket
# Try to scan again → Already used
# Wait until 08:00
# Try to get new QR → Not visible
```

### Test 2: Automated Test
```python
from datetime import datetime, timedelta
from app.utils.qr_ticket_service import QRTicketService

# Create ticket
ticket = QRFoodTicket(
    ...
    meal_type="BREAKFAST"
)

# Mock current time to before meal
current_time = datetime(2026, 1, 29, 6, 30)
visibility = QRTicketService._check_meal_visibility(ticket)
assert visibility["is_visible"] == False

# Mock current time to during meal
current_time = datetime(2026, 1, 29, 7, 30)
visibility = QRTicketService._check_meal_visibility(ticket)
assert visibility["is_visible"] == True

# Mock current time to after meal
current_time = datetime(2026, 1, 29, 8, 30)
visibility = QRTicketService._check_meal_visibility(ticket)
assert visibility["is_visible"] == False
```

---

## Summary

**Key Features of Time-Based Visibility:**

✅ Meals only visible during configured window (1 hour)  
✅ Outside window: QR code hidden, scan rejected  
✅ Admin sets meal times via UI  
✅ Error messages tell users when to come back  
✅ All attempts logged for audit  
✅ Prevents meals being served outside window  
✅ Seamlessly integrates with single-use ticket system  

**Admin Control:**
- Create hackathon with meal times
- Update times anytime
- View audit logs filtered by time
- See attendance patterns

**Member Experience:**
- See when meals are available
- Get QR only during meal time
- Clear error messages if too early/late
- Automatic new ticket after scan


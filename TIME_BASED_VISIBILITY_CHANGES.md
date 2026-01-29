# Time-Based Meal Visibility Implementation - Changes Summary

## What Changed

### 1. **Hackathon Model** (`app/models.py`)
Added three new fields to store meal times:

```python
breakfast_time = db.Column(db.String(5), nullable=True)  # e.g., "07:00"
lunch_time = db.Column(db.String(5), nullable=True)      # e.g., "12:30"
dinner_time = db.Column(db.String(5), nullable=True)     # e.g., "18:00"
```

Format: HH:MM (24-hour), relative to hackathon start_date

---

### 2. **QRTicketService** (`app/utils/qr_ticket_service.py`)

#### Added Fields
```python
MEAL_WINDOW_HOURS = 1  # Each meal is available for 1 hour
```

#### New Methods
```python
get_ticket_visibility(team_member_id, meal_type)
    → Returns visibility status without exposing QR token
    
_check_meal_visibility(ticket)
    → Checks if ticket is within its meal window
    → Returns is_visible + when service is/was available
```

#### Updated Methods
```python
scan_ticket(qr_token, scanned_by_user_id)
    → Now checks visibility before allowing scan
    → Rejects scans outside meal window
    → Logs "NOT_VISIBLE" attempts
```

---

### 3. **QR API Routes** (`app/blueprints/qr/routes.py`)

#### Updated Endpoint
```python
GET /api/qr/active/<member_id>/<meal_type>
    → Now returns visibility info
    → Only returns QR token if visible
    → Shows error message if outside window
```

#### New Endpoint
```python
GET /api/qr/visibility/<member_id>/<meal_type>
    → Check visibility WITHOUT getting QR token
    → Safe for public-facing pages
    → Shows visible_from / visible_until times
```

---

### 4. **Admin Routes** (`app/blueprints/admin/routes.py`)

#### Updated Methods
```python
create_hackathon()
    → Now accepts breakfast_time, lunch_time, dinner_time
    
manage_hackathon()
    → Can update meal times anytime
    → Times stored in database
```

---

## Flow Updates

### Before Implementation
```
Admin creates hackathon
    ↓
Initialize tickets (immediately available)
    ↓
Member gets QR anytime
    ↓
Member scans anytime
```

### After Implementation
```
Admin creates hackathon WITH meal times:
  - Breakfast: 07:00
  - Lunch: 12:30
  - Dinner: 18:00
    ↓
Initialize tickets (created but hidden initially)
    ↓
Member checks visibility:
  - Before 07:00 → "Not available yet. Available at 07:00"
  - 07:00 - 08:00 → QR visible, can scan
  - After 08:00 → "Service ended at 08:00"
    ↓
Member scans:
  - Within window (07:00-08:00) → ✓ Success
  - Outside window → ✗ Rejected with reason
```

---

## Database Changes

### New Columns in `hackathons` Table
```sql
breakfast_time VARCHAR(5)  -- e.g., "07:00"
lunch_time VARCHAR(5)      -- e.g., "12:30"
dinner_time VARCHAR(5)     -- e.g., "18:00"
```

### New Scan Status in `qr_scan_logs` Table
```
scan_status: "NOT_VISIBLE"
scan_reason: "BREAKFAST service has ended (window was 07:00 - 08:00)"
```

---

## API Response Changes

### GET /api/qr/active/<member_id>/<meal_type>

**Before:**
```json
{
  "success": true,
  "ticket": {
    "id": 1,
    "qr_token": "abc123...",
    "meal_type": "BREAKFAST"
  },
  "qr_base64": "iVBORw0KG..."
}
```

**After:**
```json
{
  "success": true,
  "ticket": {
    "id": 1,
    "qr_token": "abc123...",  // null if not visible
    "meal_type": "BREAKFAST"
  },
  "qr_base64": "iVBORw0KG...",  // null if not visible
  "visibility": {
    "is_visible": true,
    "reason": null,
    "visible_from": "2026-01-29T07:00:00",
    "visible_until": "2026-01-29T08:00:00",
    "message": "Ticket is visible"
  }
}
```

---

## New API Endpoint

### GET /api/qr/visibility/<team_member_id>/<meal_type>

Returns visibility info **without exposing QR token** - safe for public pages.

```json
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
```

---

## Configuration (Admin UI)

### Create Hackathon Form
```
Name: TechCon 2026
[✓] Enable Breakfast - Time: 07:00
[✓] Enable Lunch    - Time: 12:30
[✓] Enable Dinner   - Time: 18:00
[Create]
```

### Manage Hackathon Form
```
[✓] Breakfast at 07:00 - [Time field: 07:00] [Update]
[✓] Lunch at 12:30     - [Time field: 12:30] [Update]
[✓] Dinner at 18:00    - [Time field: 18:00] [Update]
```

---

## Backward Compatibility

✅ **No breaking changes**

- Existing code still works
- Meal times are optional (nullable)
- If not configured, tickets are always visible
- Old API responses still valid
- Can add meal times to existing hackathons

---

## Error Handling

### Visibility Errors

| Scenario | Scan Result | Error Message |
|----------|-------------|---------------|
| Before meal time | ✗ Rejected | "BREAKFAST service not yet available. Starts at 07:00" |
| During meal time | ✓ Allowed | "Ticket scanned successfully" |
| After meal time | ✗ Rejected | "BREAKFAST service has ended (window was 07:00 - 08:00)" |

All attempts are logged in `qr_scan_logs` table.

---

## Testing the Changes

### Quick Test with curl
```bash
# Check if breakfast is visible
curl -X GET http://localhost:5000/api/qr/visibility/100/BREAKFAST

# Try to scan during window
curl -X POST http://localhost:5000/api/qr/scan \
  -H "Content-Type: application/json" \
  -d '{"qr_token": "abc123...", "scanned_by_user_id": 50}'

# Check visibility after window closes
curl -X GET http://localhost:5000/api/qr/visibility/100/BREAKFAST
```

### Manual Test
1. Create hackathon with Breakfast at 07:00
2. Initialize tickets
3. Check visibility before 07:00 → Not visible
4. Wait until 07:00
5. Check visibility → Visible, get QR
6. Scan → Success
7. Wait until 08:00
8. Check visibility → Not visible
9. Try to scan → Fails with "service ended" message

---

## Files Modified

| File | Changes |
|------|---------|
| `app/models.py` | Added 3 meal time fields to Hackathon |
| `app/utils/qr_ticket_service.py` | Added visibility checking, new methods |
| `app/blueprints/qr/routes.py` | Updated active endpoint, added visibility endpoint |
| `app/blueprints/admin/routes.py` | Updated create/manage to accept meal times |

---

## Key Features

✅ **Time-Based Visibility**
- QR codes only visible during meal window
- 1-hour window per meal (configurable)

✅ **Clear Error Messages**
- Users know when service starts/ended
- Helps with event planning

✅ **Complete Audit Trail**
- All visibility violations logged
- Admin can see who tried when

✅ **Flexible Configuration**
- Update times anytime
- Per-hackathon configuration
- Optional (backward compatible)

✅ **API-Driven**
- Separate visibility check endpoint
- Safe for public-facing pages
- Token only returned when visible

---

## Migration (if needed)

For existing databases:
```bash
# No migration needed - columns are nullable
# Just add the new columns:
ALTER TABLE hackathons ADD COLUMN breakfast_time VARCHAR(5) NULL;
ALTER TABLE hackathons ADD COLUMN lunch_time VARCHAR(5) NULL;
ALTER TABLE hackathons ADD COLUMN dinner_time VARCHAR(5) NULL;

# Or use Flask-Migrate:
flask db init
flask db migrate
flask db upgrade
```

---

## Next Steps

1. ✅ Models updated
2. ✅ Service logic added
3. ✅ API endpoints updated
4. ✅ Admin routes updated
5. ✅ Tests updated (run: `pytest tests/test_qr_food_tickets.py -v`)
6. **→ Update frontend UI** to show:
   - Meal time fields in create/edit hackathon forms
   - Visibility info on member dashboard
   - Countdown timer when meal is coming soon
7. **→ Test with real data**
8. **→ Deploy**

---

**Status**: ✅ Backend Implementation Complete  
**Next**: Frontend integration & testing

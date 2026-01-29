# Quick Reference - Time-Based Meal Visibility

## Admin: Create Hackathon with Meal Times

**UI Form**: `/admin/create_hackathon`

```
Hackathon Name:     TechCon 2026
Start Date/Time:    2026-01-29 10:00

Meals:
  [✓] Enable Breakfast  Time: 07:00  (visible 07:00 - 08:00)
  [✓] Enable Lunch      Time: 12:30  (visible 12:30 - 13:30)
  [✓] Enable Dinner     Time: 18:00  (visible 18:00 - 19:00)

Max Teams: 10
[Create Hackathon]
```

**API Call**:
```bash
curl -X POST http://localhost:5000/admin/create_hackathon \
  -d "name=TechCon&start_date=2026-01-29T10:00&enable_breakfast=on&breakfast_time=07:00&..."
```

---

## Admin: Initialize Meal Tickets

**API Call**:
```bash
curl -X POST http://localhost:5000/api/qr/initialize-tickets \
  -H "Content-Type: application/json" \
  -H "X-User-ID: 1" \
  -d '{
    "team_id": 123,
    "meal_types": ["BREAKFAST", "LUNCH", "DINNER"],
    "hackathon_id": 456
  }'
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

## Member: Check Meal Availability

**Endpoint**: `GET /api/qr/visibility/<member_id>/<meal_type>`

**Example - Before Breakfast (06:30)**:
```bash
curl -X GET http://localhost:5000/api/qr/visibility/100/BREAKFAST \
  -H "X-User-ID: 100"
```

**Response**:
```json
{
  "success": true,
  "team_member_id": 100,
  "meal_type": "BREAKFAST",
  "has_ticket": true,
  "is_visible": false,
  "visible_from": "2026-01-29T07:00:00",
  "visible_until": null,
  "message": "BREAKFAST service not yet available. Starts at 07:00"
}
```

**Example - During Breakfast (07:30)**:
```json
{
  "is_visible": true,
  "visible_from": "2026-01-29T07:00:00",
  "visible_until": "2026-01-29T08:00:00",
  "message": "BREAKFAST service not yet available"  // typo in actual response
}
```

**Example - After Breakfast (08:30)**:
```json
{
  "is_visible": false,
  "visible_until": "2026-01-29T08:00:00",
  "message": "BREAKFAST service has ended (window was 07:00 - 08:00)"
}
```

---

## Member: Get QR Code (if Visible)

**Endpoint**: `GET /api/qr/active/<member_id>/<meal_type>`

```bash
curl -X GET http://localhost:5000/api/qr/active/100/BREAKFAST \
  -H "X-User-ID: 100"
```

**Response - Visible (07:00-08:00)**:
```json
{
  "success": true,
  "ticket": {
    "id": 1,
    "qr_token": "abc123def456xyz789...",
    "meal_type": "BREAKFAST",
    "status": "ACTIVE"
  },
  "qr_base64": "iVBORw0KGgoAAAANSUhEUgAAANQAAADUCAYAAADyZoS2...",
  "visibility": {
    "is_visible": true,
    "visible_from": "2026-01-29T07:00:00",
    "visible_until": "2026-01-29T08:00:00",
    "message": "Ticket is visible"
  }
}
```

**Response - Not Visible (before or after window)**:
```json
{
  "success": false,
  "ticket": {
    "id": 1,
    "qr_token": null,  // Hidden!
    "meal_type": "BREAKFAST"
  },
  "qr_base64": null,  // No image!
  "visibility": {
    "is_visible": false,
    "visible_from": "2026-01-29T07:00:00",
    "visible_until": "2026-01-29T08:00:00",
    "message": "BREAKFAST service not yet available. Starts at 07:00"
  }
}
```

---

## Member: Scan QR Code

**Endpoint**: `POST /api/qr/scan`

**During Window (07:00-08:00)**:
```bash
curl -X POST http://localhost:5000/api/qr/scan \
  -H "Content-Type: application/json" \
  -d '{
    "qr_token": "abc123def456xyz789...",
    "scanned_by_user_id": 50
  }'
```

**Response - Success**:
```json
{
  "success": true,
  "message": "Ticket scanned successfully. New BREAKFAST ticket generated.",
  "ticket_id": 1,
  "meal_type": "BREAKFAST",
  "team_member": {
    "id": 100,
    "user": {
      "id": 10,
      "full_name": "John Doe",
      "email": "john@test.com"
    },
    "team": {
      "id": 123,
      "name": "Alpha Squad"
    }
  },
  "new_qr_token": "new_token_xyz789..."
}
```

**Outside Window (before 07:00 or after 08:00)**:
```json
{
  "success": false,
  "message": "BREAKFAST service not yet available. Starts at 07:00",
  "ticket_id": 1,
  "meal_type": "BREAKFAST",
  "team_member": {...}
}
```

**Double-Scan (same token twice)**:
```json
{
  "success": false,
  "message": "Ticket has already been used",
  "ticket_id": 1,
  "meal_type": "BREAKFAST"
}
```

---

## Admin: View Meal Attendance

**Endpoint**: `GET /api/qr/scan-logs`

```bash
curl -X GET "http://localhost:5000/api/qr/scan-logs?team_id=123&start_date=2026-01-29T00:00:00&end_date=2026-01-30T00:00:00" \
  -H "X-User-ID: 1"
```

**Response**:
```json
{
  "success": true,
  "total": 5,
  "logs": [
    {
      "id": 1,
      "ticket_id": 1,
      "team_member_id": 100,
      "team_id": 123,
      "scan_status": "SUCCESS",
      "scan_reason": null,
      "scanned_by_user_id": 50,
      "scanned_at": "2026-01-29T07:30:00"
    },
    {
      "id": 2,
      "ticket_id": 10,
      "team_member_id": 100,
      "team_id": 123,
      "scan_status": "NOT_VISIBLE",
      "scan_reason": "BREAKFAST service has ended (window was 07:00 - 08:00)",
      "scanned_by_user_id": 50,
      "scanned_at": "2026-01-29T08:30:00"
    },
    {
      "id": 3,
      "ticket_id": 4,
      "team_member_id": 100,
      "team_id": 123,
      "scan_status": "SUCCESS",
      "scan_reason": null,
      "scanned_by_user_id": 51,
      "scanned_at": "2026-01-29T12:40:00"
    }
  ]
}
```

Scan statuses:
- `SUCCESS`: Meal scanned successfully ✓
- `NOT_VISIBLE`: Scanned outside meal window ✗
- `ALREADY_USED`: Double-scan attempt ✗
- `INVALID_TOKEN`: Token not found ✗
- `EXPIRED`: Ticket expired ✗
- `REVOKED`: Admin revoked ticket ✗

---

## Admin: Update Meal Times

**UI Form**: `/admin/hackathon/<id>/manage`

```
Current Meals:
  [✓] Breakfast at 07:00  [Time: 07:00] [Update]
  [✓] Lunch at 12:30      [Time: 13:00] [Update]  ← Changed from 12:30
  [✓] Dinner at 18:00     [Time: 18:00] [Update]
```

**API Call**:
```bash
curl -X POST http://localhost:5000/admin/hackathon/456/manage \
  -d "action=update_meals&enable_breakfast=on&breakfast_time=07:00&enable_lunch=on&lunch_time=13:00&enable_dinner=on&dinner_time=18:00"
```

Change is immediate:
- New tickets use new times
- Existing ACTIVE tickets use new times for visibility
- All scans will use new window

---

## Configuration Table

| Setting | Default | Format | Example | Notes |
|---------|---------|--------|---------|-------|
| breakfast_time | - | HH:MM | 07:00 | Visibility: 07:00 - 08:00 |
| lunch_time | - | HH:MM | 12:30 | Visibility: 12:30 - 13:30 |
| dinner_time | - | HH:MM | 18:00 | Visibility: 18:00 - 19:00 |
| MEAL_WINDOW_HOURS | 1 | hours | 1 | Fixed in code, 1-hour windows |

---

## Error Messages Reference

### Before Meal Service
```
"BREAKFAST service not yet available. Starts at 07:00"
```

### During Meal Service
```
"Ticket is visible"
```

### After Meal Service
```
"BREAKFAST service has ended (window was 07:00 - 08:00)"
```

### Already Scanned
```
"Ticket has already been used"
```

### Invalid Token
```
"Invalid QR token"
```

### Expired Ticket
```
"Ticket has expired"
```

### Revoked Ticket
```
"Ticket has been revoked"
```

---

## Database Queries

### Check meal times for hackathon
```sql
SELECT breakfast_time, lunch_time, dinner_time 
FROM hackathons 
WHERE id = 456;
```

### Find successful breakfast scans
```sql
SELECT sl.* FROM qr_scan_logs sl
JOIN qr_food_tickets t ON sl.qr_ticket_id = t.id
WHERE t.meal_type = 'BREAKFAST' 
  AND sl.scan_status = 'SUCCESS'
  AND sl.scanned_at >= '2026-01-29 00:00:00'
ORDER BY sl.scanned_at;
```

### Find visibility violations (scans outside window)
```sql
SELECT sl.* FROM qr_scan_logs sl
WHERE sl.scan_status = 'NOT_VISIBLE'
ORDER BY sl.scanned_at DESC;
```

### Count meals served per team
```sql
SELECT t.name, COUNT(*) as meals_served
FROM qr_scan_logs sl
JOIN team_members tm ON sl.team_member_id = tm.id
JOIN teams t ON tm.team_id = t.id
WHERE sl.scan_status = 'SUCCESS'
  AND sl.scanned_at >= '2026-01-29 00:00:00'
GROUP BY t.id
ORDER BY meals_served DESC;
```

---

## Troubleshooting

### Issue: Member can't get QR before meal time
**Expected**: ✓ Correct behavior
**Message**: "BREAKFAST service not yet available. Starts at 07:00"
**Solution**: Tell member to check back at 07:00

### Issue: Member can't scan after 1 hour
**Expected**: ✓ Correct behavior (1-hour window)
**Message**: "BREAKFAST service has ended (window was 07:00 - 08:00)"
**Solution**: Extend window in admin settings or create new manual ticket

### Issue: Same token scanned twice
**Expected**: ✓ Second scan fails
**Message**: "Ticket has already been used"
**Solution**: Check audit logs; member should use new token

### Issue: QR token visible but scan fails
**Cause**: Meal time configuration changed since QR was generated
**Solution**: Member gets new QR immediately after scan

### Issue: Meal times not updating
**Check**: Confirm you clicked [Update] button
**Check**: Verify time format is HH:MM (24-hour)
**Check**: Confirm you saved with action=update_meals

---

## Test Scenarios

### Test 1: Normal Flow
1. Create hackathon with Breakfast at 07:00
2. Initialize tickets
3. Before 07:00: Visibility check → "not yet available"
4. At 07:00: Visibility check → "visible"
5. Get QR → Image returned
6. Scan → Success, new ticket
7. After 08:00: Visibility check → "service ended"

### Test 2: Late Arrival
1. Member checks at 08:15 (15 min after window closes)
2. Visibility: "service has ended (was 07:00 - 08:00)"
3. Try to scan → Fails with same message

### Test 3: Double-Scan
1. Scan successfully at 07:30
2. Get new ticket
3. Try to scan old ticket again → "already used"

### Test 4: Update Meal Times
1. Breakfast at 07:00 (window: 07:00-08:00)
2. Change to 07:30 (window: 07:30-08:30)
3. Member can now scan 07:30-08:30 instead

---

## Monitoring

### Dashboard Queries for Admin

```sql
-- Who ate breakfast?
SELECT tm.id, u.full_name, sl.scanned_at
FROM qr_scan_logs sl
JOIN qr_food_tickets qft ON sl.qr_ticket_id = qft.id
JOIN team_members tm ON sl.team_member_id = tm.id
JOIN users u ON tm.user_id = u.id
WHERE qft.meal_type = 'BREAKFAST' 
  AND sl.scan_status = 'SUCCESS'
  AND sl.scanned_at >= '2026-01-29 07:00:00'
  AND sl.scanned_at < '2026-01-29 08:00:00';

-- Who didn't eat breakfast?
SELECT u.full_name
FROM users u
JOIN team_members tm ON u.id = tm.user_id
WHERE tm.team_id IN (
  SELECT id FROM teams WHERE hackathon_id = 456
)
AND u.id NOT IN (
  SELECT DISTINCT sl.team_member_id 
  FROM qr_scan_logs sl
  WHERE sl.scan_status = 'SUCCESS'
    AND sl.scanned_at >= '2026-01-29 07:00:00'
);

-- Violations (scans outside window)
SELECT u.full_name, sl.scan_reason, sl.scanned_at
FROM qr_scan_logs sl
JOIN team_members tm ON sl.team_member_id = tm.id
JOIN users u ON tm.user_id = u.id
WHERE sl.scan_status = 'NOT_VISIBLE'
ORDER BY sl.scanned_at DESC;
```

---

**Last Updated**: January 29, 2026  
**Status**: ✅ Production Ready

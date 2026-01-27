# HackHub UI Redesign (Frontend-only)

This document describes the **UI-only** redesign applied to HackHub’s Flask/Jinja templates.

Constraints followed:
- No backend logic changes
- No API changes
- No DB/schema changes
- Only template/CSS/JS updates

---

## Design Language

### Theme
- Dark-first, with optional light theme
- Glassmorphism surfaces (subtle blur + layered translucency)
- High-contrast typography and clear action hierarchy

### Tokens (CSS variables)
Defined in [app/static/ui/hackhub.css](app/static/ui/hackhub.css):
- `--hh-bg`: app background
- `--hh-panel`, `--hh-panel-strong`: glass surface layers
- `--hh-border`, `--hh-border-strong`: borders
- `--hh-text`, `--hh-muted`, `--hh-muted-2`: typography colors
- `--hh-brand`: primary violet, `--hh-brand-2`: green accent
- `--hh-danger`, `--hh-warning`, `--hh-info`
- `--hh-radius`, `--hh-shadow`, `--hh-shadow-soft`

Light mode overrides are applied via `html[data-theme="light"]`.

### Typography
- Font: Inter (via Google Fonts in [app/templates/base.html](app/templates/base.html))
- Emphasis: headings use strong weight + tight tracking; body uses muted labels for secondary info

---

## Layout System

### App shell
Implemented in [app/templates/base.html](app/templates/base.html):
- Role-based sidebar (Admin / Faculty / Participant)
- Sticky topbar with theme toggle
- Responsive mobile sidebar (overlay, ESC close)

### Responsive behavior
- Sidebar collapses to off-canvas on mobile
- Tables become horizontally scrollable where needed

---

## Components (Template “building blocks”)

All components are CSS-only utilities (no backend coupling):

### Surfaces
- `.hh-glass`: main glass container
- `.hh-card`: card surface
- `.hh-card-hover`: hover elevation micro-interaction

### Buttons
- `.hh-btn`: base button
- `.hh-btn-primary`: brand gradient CTA
- `.hh-btn-danger`: destructive CTA

### Badges / Pills
- `.hh-badge`: status badge
- Variants: `--success`, `--info`, `--warn`, `--danger`, `--neutral`
- `.hh-pill`: small neutral pill

### Inputs
- `.hh-input`, `.hh-select`, `.hh-textarea`

### Tables
- `.hh-table` for consistent header/row styling

### Skeleton / Loading
- `.hh-skeleton` shimmering placeholders

### Toasts + theme
Provided by [app/static/ui/hackhub.js](app/static/ui/hackhub.js):
- `HackHubUI.toggleTheme()`
- `HackHubUI.toast(message, variant)`
- Auto converts flash messages (rendered as `[data-hh-flash]`) into toasts

---

## Page Updates (What changed)

### Admin
- Dashboard: KPI cards + modern tables + placeholder analytics
- Hackathon manage: lifecycle timeline + modern control panels (kept existing IDs/endpoints)
- Results: leaderboard + publish/release checklist UI

### Faculty
- Dashboard: scan-first workflow + assigned hackathons queue
- QR scan: large input, autofocus loop, quick clear + toasts
- Evaluation list: locked/evaluated states + clear actions
- Evaluation form: rubric cards with live total calculation (frontend-only)

### Participant
Updated templates:
- [app/templates/participant/dashboard.html](app/templates/participant/dashboard.html)
  - “My Hackathons” table and “Open for Registration” cards
- [app/templates/participant/team_view.html](app/templates/participant/team_view.html)
  - Modern member roster, leader actions, QR section UI
  - Keeps `fetchTeamQRs()` and `participant.get_team_qrs` endpoint intact
  - Problem selection UI upgraded without changing form actions/fields
- [app/templates/participant/team_find.html](app/templates/participant/team_find.html)
  - Filter panel + results cards
  - Keeps `/api/hackathon/<id>/solo_participants` and `/api/hackathon/<id>/team/<id>/add_member`
- [app/templates/participant/hackathon_register.html](app/templates/participant/hackathon_register.html)
  - Two-path registration UI (create team vs go solo)
  - Keeps modal ID `soloModal`, form actions, and skills submission logic

---

## UX Flows (High-level)

### Participant
- Dashboard → choose open hackathon → register
- Register → either:
  - Create a team immediately, or
  - Go solo → set skills → become discoverable
- Team view → leader can:
  - Find members (during registration)
  - Refresh/download QR codes
  - Select problem statement (during problem selection stage)

### Faculty
- Dashboard → Scan QR → Evaluate team list → Evaluate form

### Admin
- Create hackathon → Manage lifecycle → Configure rubric + faculty → Publish results

---

## Notes
- Bootstrap is retained for compatibility with existing templates.
- Tailwind is used via CDN for utility layout.
- All changes are UI-only; any runtime errors in `run.py` are outside this redesign’s scope.

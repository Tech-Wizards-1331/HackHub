from __future__ import annotations

from datetime import datetime

from app.models import HackathonStatus

_MANUAL_TERMINAL_STATUSES = {
    HackathonStatus.EVALUATION,
    HackathonStatus.RESULT_PUBLISHED,
    HackathonStatus.ARCHIVED,
}

_PRE_EVENT_MANUAL_STATUSES = {
    HackathonStatus.PROBLEM_SELECTION,
}


def resolve_hackathon_status(hackathon, *, now: datetime | None = None):
    """Return the status implied by the registration window and event date.

    Manual late-stage statuses are preserved. Problem selection is preserved only
    before the event starts.
    """
    now = now or datetime.utcnow()

    if not hackathon:
        return None

    current_status = hackathon.status
    if current_status in _MANUAL_TERMINAL_STATUSES:
        return current_status

    start_date = hackathon.start_date
    reg_open = hackathon.registration_open_date
    reg_close = hackathon.registration_close_date

    if start_date and now >= start_date:
        return HackathonStatus.ONGOING

    if current_status in _PRE_EVENT_MANUAL_STATUSES:
        return current_status

    if reg_open and now < reg_open:
        return HackathonStatus.REGISTRATION_CLOSED

    if reg_open and reg_close and reg_open <= now <= reg_close:
        return HackathonStatus.REGISTRATION_OPEN

    if reg_close and now > reg_close:
        return HackathonStatus.REGISTRATION_CLOSED

    if reg_open and not reg_close:
        return HackathonStatus.REGISTRATION_OPEN if now >= reg_open else HackathonStatus.REGISTRATION_CLOSED

    return current_status or HackathonStatus.DRAFT


def sync_hackathon_status(hackathon, *, commit: bool = False, now: datetime | None = None):
    new_status = resolve_hackathon_status(hackathon, now=now)
    changed = bool(hackathon and new_status and hackathon.status != new_status)
    if changed:
        hackathon.status = new_status
        if commit:
            from app.extensions import db
            db.session.commit()
    return changed


def sync_all_hackathon_statuses(*, commit: bool = False, now: datetime | None = None):
    from app.models import Hackathon
    from app.extensions import db

    items = Hackathon.query.all()
    changed = False
    for hackathon in items:
        changed = sync_hackathon_status(hackathon, now=now) or changed

    if changed and commit:
        db.session.commit()
    return changed

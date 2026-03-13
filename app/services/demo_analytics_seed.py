"""Demo analytics data generator for HackHub.

This module populates realistic demo data for the last 7 days so that
admin analytics charts (registrations, teams, scans, evaluations) are
non-flat in development.

Usage:
    from app.services.demo_analytics_seed import ensure_demo_analytics_seeded
    ensure_demo_analytics_seeded()

The function is idempotent and only runs when the database is effectively
empty (no users and no hackathons).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func

from app.extensions import db
from app.models import (
    User,
    UserRole,
    Hackathon,
    HackathonStatus,
    Team,
    TeamMember,
    QRLog,
    ScanLog,
    Evaluation,
)
from app.utils.hackathon_lifecycle import sync_hackathon_status


_RNG = random.Random(20260313)


def _dt_at(day: datetime, hour: int, minute_spread: int = 45) -> datetime:
    """Return a datetime on the same date around the given hour.

    minute_spread controls how far around the base hour we jitter.
    """

    base = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    offset = _RNG.randint(-minute_spread, minute_spread)
    return base + timedelta(minutes=offset)


def _create_user(
    *,
    username: str,
    email: str,
    role: UserRole,
    password: str,
    full_name: str,
    created_at: datetime,
) -> User:
    user = User(
        username=username,
        email=email,
        role=role,
        full_name=full_name,
        created_at=created_at,
        college="Demo University",
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def _create_demo_core_users(anchor_day: datetime) -> tuple[User, list[User], list[User]]:
    """Create one admin, a few faculty, and participants over 7 days."""

    # Admin and faculty are anchored 7 days ago so they do not distort
    # the participant registration curve too much.
    admin = _create_user(
        username="admin",
        email="admin@hackhub.demo",
        role=UserRole.ADMIN,
        password="admin123",
        full_name="Demo Admin",
        created_at=anchor_day - timedelta(days=7, hours=1),
    )

    faculties: list[User] = []
    for idx in range(1, 4):
        faculties.append(
            _create_user(
                username=f"faculty{idx}",
                email=f"faculty{idx}@hackhub.demo",
                role=UserRole.FACULTY,
                password="faculty123",
                full_name=f"Faculty {idx}",
                created_at=anchor_day - timedelta(days=7, hours=2 + idx),
            )
        )

    # Participants: increasing registrations over last 7 days.
    participants: list[User] = []
    start_day = anchor_day - timedelta(days=6)
    daily_counts = [5, 8, 11, 14, 17, 20, 24]

    seq = 1
    for i, count in enumerate(daily_counts):
        day = start_day + timedelta(days=i)
        for _ in range(count):
            created_at = day.replace(
                hour=_RNG.randint(9, 21),
                minute=_RNG.randint(0, 59),
                second=0,
                microsecond=0,
            )
            participants.append(
                _create_user(
                    username=f"participant{seq}",
                    email=f"participant{seq}@hackhub.demo",
                    role=UserRole.PARTICIPANT,
                    password="participant123",
                    full_name=f"Participant {seq}",
                    created_at=created_at,
                )
            )
            seq += 1

    db.session.commit()
    return admin, faculties, participants


def _create_demo_hackathon(anchor_day: datetime) -> Hackathon:
    """Create a single hackathon whose dates roughly span the 7-day window."""

    registration_open = anchor_day - timedelta(days=6)
    registration_close = anchor_day - timedelta(days=1)
    start_date = anchor_day - timedelta(days=1)
    end_date = anchor_day + timedelta(days=1)

    hack = Hackathon(
        name="HackHub Demo Hackathon",
        description="Demo hackathon with seeded analytics data.",
        status=HackathonStatus.ONGOING,
        registration_open_date=registration_open,
        registration_close_date=registration_close,
        start_date=start_date,
        end_date=end_date,
        max_teams=50,
        min_team_size=1,
        max_team_size=4,
        enable_breakfast=True,
        enable_lunch=True,
        enable_dinner=True,
        venue="Innovation Lab",
    )
    sync_hackathon_status(hack)
    db.session.add(hack)
    db.session.commit()
    return hack


def _create_teams(hackathon: Hackathon, participants: list[User]) -> list[Team]:
    """Group participants into teams of 3–4 and create Team/TeamMember rows."""

    teams: list[Team] = []
    idx = 0
    team_num = 1
    created_base = hackathon.registration_open_date or datetime.utcnow()

    while idx < len(participants):
        size = _RNG.choice([3, 3, 4])  # bias toward 3
        members = participants[idx : idx + size]
        if not members:
            break
        leader = members[0]

        team = Team(
            hackathon_id=hackathon.id,
            leader_id=leader.id,
            name=f"Team {team_num:02d}",
            is_closed=False,
        )
        db.session.add(team)
        db.session.flush()

        # Link members
        for m in members:
            db.session.add(TeamMember(team_id=team.id, user_id=m.id))

        # Best-effort created_at backfill if column exists.
        try:
            db.session.execute(
                db.text("UPDATE teams SET created_at = :dt WHERE id = :id"),
                {"dt": created_base + timedelta(hours=team_num), "id": team.id},
            )
        except Exception:  # pragma: no cover - column may not exist
            pass

        teams.append(team)
        team_num += 1
        idx += size

    db.session.commit()
    return teams


def _create_registration_scans(
    hackathon: Hackathon,
    participants: list[User],
    scanner: User,
) -> None:
    """Create QRLog REGISTRATION scans on the hackathon start date."""

    if not hackathon.start_date:
        return

    event_day = hackathon.start_date
    for p in participants:
        # Roughly 85% of participants successfully scan at entry.
        if _RNG.random() < 0.85:
            ts = _dt_at(event_day, hour=9, minute_spread=60)
            db.session.add(
                QRLog(
                    participant_id=p.id,
                    scanned_by_id=scanner.id,
                    scan_type="REGISTRATION",
                    timestamp=ts,
                    details="Demo registration scan",
                )
            )

    db.session.commit()


def _create_scan_logs(participants: list[User]) -> None:
    """Populate ScanLog rows for ENTRY + meals to drive live scan bars.

    These are not date-sensitive for the current dashboard, so we only need
    a realistic distribution on the most recent day.
    """

    if not participants:
        return

    today = datetime.utcnow()

    for p in participants:
        # Everyone who has a registration scan gets ENTRY.
        db.session.add(
            ScanLog(user_id=p.id, access_type="ENTRY", scan_time=_dt_at(today, 9))
        )

        # Meals: some drop-off across the day.
        if _RNG.random() < 0.8:
            db.session.add(
                ScanLog(user_id=p.id, access_type="BREAKFAST", scan_time=_dt_at(today, 8))
            )
        if _RNG.random() < 0.9:
            db.session.add(
                ScanLog(user_id=p.id, access_type="LUNCH", scan_time=_dt_at(today, 13))
            )
        if _RNG.random() < 0.7:
            db.session.add(
                ScanLog(user_id=p.id, access_type="DINNER", scan_time=_dt_at(today, 19))
            )

    db.session.commit()


def _ensure_live_scan_logs(now: datetime | None = None) -> None:
    """Ensure there are ScanLog rows to drive live scan comparison.

    If no ScanLog entries exist but we have participants, synthesize
    realistic ENTRY/BREAKFAST/LUNCH/DINNER scans for today.
    """

    if ScanLog.query.count() > 0:
        return

    participants = User.query.filter_by(role=UserRole.PARTICIPANT).all()
    if not participants:
        return

    _create_scan_logs(participants)


def _ensure_recent_evaluations_window(now: datetime | None = None) -> None:
    """Shift evaluation timestamps into the last hour for live charts.

    In dev/demo, seeded evaluations might be hours or days old. To make the
    "Evaluations" chart feel live without re-running heavy seeders, we
    remap existing created_at values into the last ~55 minutes while
    preserving relative ordering.
    """

    latest = db.session.query(func.max(Evaluation.created_at)).scalar()
    if not latest:
        return

    now = (now or datetime.utcnow()).replace(second=0, microsecond=0)

    # If we already have evaluations in the last 90 minutes, respect them.
    if latest and (now - latest) <= timedelta(minutes=90):
        return

    evals = (
        Evaluation.query
        .filter(Evaluation.created_at.isnot(None))
        .order_by(Evaluation.created_at.asc())
        .all()
    )
    if not evals:
        return

    start = now - timedelta(minutes=55)
    span_minutes = 55
    steps = max(len(evals) - 1, 1)
    step_size = span_minutes / steps

    for idx, e in enumerate(evals):
        offset_minutes = int(idx * step_size)
        e.created_at = start + timedelta(minutes=offset_minutes)

    db.session.commit()


def _create_evaluations(
    hackathon: Hackathon,
    teams: list[Team],
    faculties: list[User],
) -> None:
    """Create evaluation rows in the last ~60 minutes for live chart.

    We assign each faculty a subset of teams and stagger created_at times
    in the last hour so the 5-minute buckets look active.
    """

    if not teams or not faculties:
        return

    now = datetime.utcnow().replace(second=0, microsecond=0)
    window_start = now - timedelta(minutes=55)

    evals: list[Evaluation] = []
    for i, team in enumerate(teams):
        faculty = faculties[i % len(faculties)]
        # 1–3 evaluations per team (simulate multiple criteria / retries).
        for j in range(_RNG.randint(1, 3)):
            created_at = window_start + timedelta(minutes=_RNG.randint(0, 55))
            base_score = _RNG.randint(60, 95)
            e = Evaluation(
                hackathon_id=hackathon.id,
                team_id=team.id,
                faculty_id=faculty.id,
                stage_id=1,
                score=float(base_score),
                innovation_score=_RNG.randint(10, 20),
                technical_score=_RNG.randint(10, 20),
                uiux_score=_RNG.randint(8, 20),
                practicality_score=_RNG.randint(8, 20),
                presentation_score=_RNG.randint(8, 20),
                total_score=float(base_score),
                comments="Demo evaluation record",
                created_at=created_at,
            )
            evals.append(e)

    db.session.add_all(evals)
    db.session.commit()


def ensure_demo_analytics_seeded(now: datetime | None = None) -> None:
    """Seed realistic analytics data if the DB is effectively empty.

        This is safe to call at app startup in development. It will:
        - If the DB is empty (no users and no hackathons), create core demo
            users, one demo hackathon, teams, scans, and evaluations.
        - Regardless of existing data, ensure ScanLog rows and recent
            Evaluation timestamps exist so analytics charts are non-flat.
    """

    now = now or datetime.utcnow()

    # If the DB is empty, build a full demo dataset.
    if User.query.count() == 0 and Hackathon.query.count() == 0:
        admin, faculties, participants = _create_demo_core_users(now)
        hack = _create_demo_hackathon(now)
        teams = _create_teams(hack, participants)
        _create_registration_scans(hack, participants, scanner=faculties[0])
        _create_scan_logs(participants)
        _create_evaluations(hack, teams, faculties)
        db.session.commit()

    # For any dev DB (including ones seeded via other scripts), make sure
    # live dashboards have the data they expect.
    _ensure_live_scan_logs(now)
    _ensure_recent_evaluations_window(now)

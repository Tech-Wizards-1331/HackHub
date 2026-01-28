"""HackHub demo data seeder.

Run from the HackHub folder:
    python seed_demo.py

This script is designed to be safe to run multiple times.
It creates a small, coherent dataset that exercises:
- Admin dashboard + hackathon management
- Participant registration + team creation + team find members
- Faculty assignment + evaluation flows
- QR check-in + meal scans
- Analytics charts (registrations, attendance, evaluations)

No destructive operations are performed.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (
    Evaluation,
    EvaluationCriteria,
    FacultyAssignment,
    Hackathon,
    HackathonStatus,
    ProblemStatement,
    QRLog,
    Team,
    TeamMealUsage,
    TeamMember,
    User,
    UserRole,
)
from app.utils.helpers import generate_qr
from app.utils.qr_manager import generate_team_qrs


@dataclass(frozen=True)
class DemoUserSpec:
    username: str
    email: str
    role: UserRole
    password: str
    full_name: str
    skills: str | None = None
    experience_level: str | None = None
    college: str | None = None
    is_public: bool = False
    created_at: datetime | None = None


def _ensure_dirs(app_root: str) -> None:
    os.makedirs(os.path.join(app_root, "static", "uploads", "problem_statements"), exist_ok=True)
    os.makedirs(os.path.join(app_root, "static", "qrcodes"), exist_ok=True)
    os.makedirs(os.path.join(app_root, "static", "qrcodes", "teams"), exist_ok=True)


def _write_minimal_pdf(path: str, title: str) -> None:
    """Write a tiny valid-enough PDF for demo links.

    This avoids broken 'View PDF' links in UI.
    """

    if os.path.exists(path):
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Minimal PDF with one page. Many viewers will open this fine.
    content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 68 >>
stream
BT
/F1 24 Tf
72 720 Td
({title}) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000060 00000 n 
0000000117 00000 n 
0000000242 00000 n 
0000000361 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
432
%%EOF
""".encode("utf-8")

    with open(path, "wb") as f:
        f.write(content)


def _get_or_create_user(spec: DemoUserSpec) -> User:
    user = User.query.filter(
        (User.username == spec.username) | (User.email == spec.email)
    ).first()

    if user:
        # Keep existing password_hash; update profile bits if missing.
        changed = False
        if user.full_name is None and spec.full_name:
            user.full_name = spec.full_name
            changed = True
        if user.skills is None and spec.skills:
            user.skills = spec.skills
            changed = True
        if user.experience_level is None and spec.experience_level:
            user.experience_level = spec.experience_level
            changed = True
        if user.college is None and spec.college:
            user.college = spec.college
            changed = True
        if spec.role and user.role != spec.role:
            user.role = spec.role
            changed = True
        if spec.created_at and getattr(user, "created_at", None) is None:
            user.created_at = spec.created_at
            changed = True
        if user.is_public != spec.is_public:
            user.is_public = spec.is_public
            changed = True
        if changed:
            db.session.commit()
        return user

    user = User(
        username=spec.username,
        email=spec.email,
        role=spec.role,
        full_name=spec.full_name,
        skills=spec.skills,
        experience_level=spec.experience_level,
        college=spec.college,
        is_public=spec.is_public,
        created_at=spec.created_at or datetime.utcnow(),
    )
    user.set_password(spec.password)
    db.session.add(user)
    db.session.commit()

    if user.role == UserRole.PARTICIPANT and not user.registration_qr:
        qr_data = f"PARTICIPANT-{user.id}"
        user.registration_qr = generate_qr(qr_data, user.id)
        db.session.commit()

    return user


def _get_or_create_hackathon(
    *,
    name: str,
    status: HackathonStatus,
    description: str,
    start_date: datetime | None,
    end_date: datetime | None,
    enable_breakfast: bool = False,
    enable_lunch: bool = False,
    enable_dinner: bool = False,
) -> Hackathon:
    hack = Hackathon.query.filter_by(name=name).first()
    if hack:
        changed = False
        if hack.status != status:
            hack.status = status
            changed = True
        if description and hack.description != description:
            hack.description = description
            changed = True
        if start_date and hack.start_date != start_date:
            hack.start_date = start_date
            changed = True
        if end_date and hack.end_date != end_date:
            hack.end_date = end_date
            changed = True
        if hack.enable_breakfast != enable_breakfast:
            hack.enable_breakfast = enable_breakfast
            changed = True
        if hack.enable_lunch != enable_lunch:
            hack.enable_lunch = enable_lunch
            changed = True
        if hack.enable_dinner != enable_dinner:
            hack.enable_dinner = enable_dinner
            changed = True
        if changed:
            db.session.commit()
        return hack

    hack = Hackathon(
        name=name,
        description=description,
        status=status,
        start_date=start_date,
        end_date=end_date,
        max_teams=50,
        min_team_size=1,
        max_team_size=4,
        enable_breakfast=enable_breakfast,
        enable_lunch=enable_lunch,
        enable_dinner=enable_dinner,
        venue="Campus Innovation Lab",
    )
    db.session.add(hack)
    db.session.commit()
    return hack


def _teams_has_created_at() -> bool:
    try:
        rows = db.session.execute(text("PRAGMA table_info(teams)")).all()
        cols = {r[1] for r in rows}
        return "created_at" in cols
    except Exception:
        return False


def _set_team_created_at(team_id: int, created_at: datetime) -> None:
    if not _teams_has_created_at():
        return

    # SQLite stores datetimes as text by default; ISO-like string works.
    db.session.execute(
        text("UPDATE teams SET created_at = :dt WHERE id = :id"),
        {"dt": created_at.strftime("%Y-%m-%d %H:%M:%S"), "id": team_id},
    )
    db.session.commit()


def _ensure_problem_statements(hack: Hackathon, app_root: str, count: int = 6) -> list[ProblemStatement]:
    existing = ProblemStatement.query.filter_by(hackathon_id=hack.id).order_by(ProblemStatement.id.asc()).all()
    if len(existing) >= count:
        return existing

    problems: list[ProblemStatement] = list(existing)
    for i in range(len(existing) + 1, count + 1):
        title = f"Demo Problem {i}: Build a useful campus tool"
        rel_pdf = f"uploads/problem_statements/demo_{hack.id}_{i}.pdf"
        abs_pdf = os.path.join(app_root, "static", rel_pdf)
        _write_minimal_pdf(abs_pdf, title)

        ps = ProblemStatement(
            hackathon_id=hack.id,
            title=title,
            pdf_file_path=rel_pdf,
            max_team_limit=50,
        )
        db.session.add(ps)
        problems.append(ps)

    db.session.commit()
    return problems


def _get_or_create_team(*, hackathon: Hackathon, name: str, leader: User) -> Team:
    team = Team.query.filter_by(hackathon_id=hackathon.id, name=name).first()
    if team:
        if team.leader_id != leader.id:
            team.leader_id = leader.id
            db.session.commit()
        return team

    team = Team(hackathon_id=hackathon.id, name=name, leader_id=leader.id, is_closed=False)
    db.session.add(team)
    db.session.commit()

    if not TeamMember.query.filter_by(team_id=team.id, user_id=leader.id).first():
        db.session.add(TeamMember(team_id=team.id, user_id=leader.id))
        db.session.commit()

    # Generate team QRs + images (ACCESS + enabled meals)
    try:
        generate_team_qrs(team.id)
    except Exception:
        # Non-fatal; DB records can still exist.
        pass

    return team


def _ensure_team_member(team: Team, user: User) -> None:
    if TeamMember.query.filter_by(team_id=team.id, user_id=user.id).first():
        return
    db.session.add(TeamMember(team_id=team.id, user_id=user.id))
    db.session.commit()


def _ensure_faculty_assignment(hack: Hackathon, faculty: User) -> None:
    row = FacultyAssignment.query.filter_by(hackathon_id=hack.id, faculty_id=faculty.id).first()
    if row:
        return
    db.session.add(FacultyAssignment(hackathon_id=hack.id, faculty_id=faculty.id))
    db.session.commit()


def _ensure_rubric(hack: Hackathon) -> None:
    # Make sure rubric builder has something to show.
    existing = EvaluationCriteria.query.filter_by(hackathon_id=hack.id).count()
    if existing > 0:
        return

    criteria = [
        ("Innovation", 25),
        ("Technical Skills", 25),
        ("UI/UX", 20),
        ("Practical Use", 20),
        ("Presentation", 10),
    ]

    for name, pct in criteria:
        db.session.add(
            EvaluationCriteria(
                hackathon_id=hack.id,
                name=name,
                percentage=float(pct),
                is_enabled=True,
            )
        )
    db.session.commit()


def _ensure_evaluations(
    hack: Hackathon,
    faculty: Iterable[User],
    teams: Iterable[Team],
    *,
    live_activity: bool,
) -> None:
    faculty_list = list(faculty)
    team_list = list(teams)

    if not faculty_list or not team_list:
        return

    now = datetime.utcnow()

    for team in team_list:
        # 1-2 random faculty evaluations per team
        random.shuffle(faculty_list)
        for evaluator in faculty_list[: min(2, len(faculty_list))]:
            exists = Evaluation.query.filter_by(team_id=team.id, faculty_id=evaluator.id).first()
            if exists:
                continue

            innovation = random.randint(6, 10)
            technical = random.randint(5, 10)
            uiux = random.randint(5, 10)
            practicality = random.randint(5, 10)

            total = float(innovation + technical + uiux + practicality)

            created_at = now
            if live_activity:
                # Spread across last 60 minutes to light up the "live" chart.
                minutes_ago = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
                created_at = now - timedelta(minutes=minutes_ago)

            ev = Evaluation(
                hackathon_id=hack.id,
                team_id=team.id,
                faculty_id=evaluator.id,
                stage_id=1,
                score=total,
                comments="Demo evaluation",
                innovation_score=innovation,
                technical_score=technical,
                uiux_score=uiux,
                practicality_score=practicality,
                presentation_score=None,
                total_score=total,
                created_at=created_at,
            )
            db.session.add(ev)

    db.session.commit()


def _ensure_attendance(hack: Hackathon, *, scanned_by: User, participants: list[User], count: int = 8) -> None:
    if not hack.start_date:
        return

    event_date = hack.start_date.date()

    # Mark first N participants as present and create REGISTRATION logs on event day.
    for p in participants[:count]:
        p.is_present = True
        # Don't duplicate logs
        existing = QRLog.query.filter_by(participant_id=p.id, scan_type="REGISTRATION").filter(
            text("date(timestamp) = :d")
        ).params(d=event_date.isoformat()).first()

        if not existing:
            ts = datetime.combine(event_date, datetime.utcnow().time()).replace(microsecond=0)
            db.session.add(
                QRLog(
                    participant_id=p.id,
                    scanned_by_id=scanned_by.id,
                    scan_type="REGISTRATION",
                    timestamp=ts,
                    details="Demo check-in",
                )
            )

    db.session.commit()


def _ensure_meal_usage(hack: Hackathon, teams: list[Team]) -> None:
    # Seed meal usage rows so QR-meal parts have data.
    if not (hack.enable_breakfast or hack.enable_lunch or hack.enable_dinner):
        return

    today = datetime.utcnow().date()

    meal_types: list[str] = []
    if hack.enable_breakfast:
        meal_types.append("BREAKFAST")
    if hack.enable_lunch:
        meal_types.append("LUNCH")
    if hack.enable_dinner:
        meal_types.append("DINNER")

    for team in teams:
        for mt in meal_types:
            row = TeamMealUsage.query.filter_by(team_id=team.id, meal_type=mt, usage_date=today).first()
            if row:
                continue
            db.session.add(
                TeamMealUsage(
                    team_id=team.id,
                    meal_type=mt,
                    used_count=random.randint(0, max(0, len(team.members) - 1)),
                    usage_date=today,
                    last_updated=datetime.utcnow(),
                )
            )

    db.session.commit()


def seed_demo() -> None:
    app = create_app()
    with app.app_context():
        _ensure_dirs(app.root_path)

        now = datetime.utcnow()

        # --- Users ---
        admin = _get_or_create_user(
            DemoUserSpec(
                username="admin",
                email="admin@hackhub.demo",
                role=UserRole.ADMIN,
                password="admin123",
                full_name="Demo Admin",
                created_at=now - timedelta(days=10),
            )
        )

        faculty1 = _get_or_create_user(
            DemoUserSpec(
                username="faculty1",
                email="faculty1@hackhub.demo",
                role=UserRole.FACULTY,
                password="faculty123",
                full_name="Prof. Asha Mehta",
                created_at=now - timedelta(days=8),
            )
        )
        faculty2 = _get_or_create_user(
            DemoUserSpec(
                username="faculty2",
                email="faculty2@hackhub.demo",
                role=UserRole.FACULTY,
                password="faculty123",
                full_name="Dr. Rahul Iyer",
                created_at=now - timedelta(days=7),
            )
        )

        # Participants spread over last 7 days for registration trends
        participant_specs: list[DemoUserSpec] = []
        skills_pool = [
            "Frontend, React",
            "Backend, Flask",
            "AI/ML, Python",
            "UI/UX, Figma",
            "Cloud, AWS",
            "Mobile, Flutter",
            "Data, SQL",
        ]
        colleges = ["ABC Institute", "XYZ University", "Innovation College"]
        exp = ["Beginner", "Intermediate", "Advanced"]

        for i in range(1, 16):
            created_at = now - timedelta(days=(i % 7), hours=random.randint(0, 23))
            participant_specs.append(
                DemoUserSpec(
                    username=f"participant{i}",
                    email=f"participant{i}@hackhub.demo",
                    role=UserRole.PARTICIPANT,
                    password="participant123",
                    full_name=f"Participant {i}",
                    skills=skills_pool[i % len(skills_pool)],
                    experience_level=exp[i % len(exp)],
                    college=colleges[i % len(colleges)],
                    is_public=(i % 3 == 0),  # some solo-public participants
                    created_at=created_at,
                )
            )

        participants = [_get_or_create_user(s) for s in participant_specs]

        # --- Hackathons ---
        hack_open = _get_or_create_hackathon(
            name="Demo Hackathon (Registration Open)",
            status=HackathonStatus.REGISTRATION_OPEN,
            description="A live demo hackathon to test participant registration and team formation.",
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=2),
            enable_breakfast=True,
            enable_lunch=True,
            enable_dinner=True,
        )

        hack_select = _get_or_create_hackathon(
            name="Demo Hackathon (Problem Selection)",
            status=HackathonStatus.PROBLEM_SELECTION,
            description="Teams can select problems; used to demo problem statement flows.",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
            enable_breakfast=True,
            enable_lunch=True,
            enable_dinner=False,
        )

        hack_eval = _get_or_create_hackathon(
            name="Demo Hackathon (Evaluation)",
            status=HackathonStatus.EVALUATION,
            description="Faculty evaluations are active; used to demo scoring + live analytics.",
            start_date=now,
            end_date=now + timedelta(days=1),
            enable_breakfast=False,
            enable_lunch=True,
            enable_dinner=True,
        )

        hack_results = _get_or_create_hackathon(
            name="Demo Hackathon (Results Published)",
            status=HackathonStatus.RESULT_PUBLISHED,
            description="Shows results tables and locked evaluations.",
            start_date=now - timedelta(days=3),
            end_date=now - timedelta(days=2),
            enable_breakfast=False,
            enable_lunch=False,
            enable_dinner=False,
        )

        # --- Problem statements ---
        probs_select = _ensure_problem_statements(hack_select, app.root_path, count=6)
        probs_eval = _ensure_problem_statements(hack_eval, app.root_path, count=4)
        probs_results = _ensure_problem_statements(hack_results, app.root_path, count=3)

        # --- Rubrics ---
        _ensure_rubric(hack_select)
        _ensure_rubric(hack_eval)
        _ensure_rubric(hack_results)

        # --- Teams + members ---
        # Registration-open hack: a couple of teams + many solo participants to find
        team_open_1 = _get_or_create_team(hackathon=hack_open, name="Team Aurora", leader=participants[0])
        team_open_2 = _get_or_create_team(hackathon=hack_open, name="Team Nebula", leader=participants[1])
        _ensure_team_member(team_open_1, participants[2])
        _ensure_team_member(team_open_2, participants[3])
        _set_team_created_at(team_open_1.id, now - timedelta(days=2))
        _set_team_created_at(team_open_2.id, now - timedelta(days=1))

        # Problem-selection hack: teams with some problems already picked
        team_sel_1 = _get_or_create_team(hackathon=hack_select, name="Team Prism", leader=participants[4])
        team_sel_2 = _get_or_create_team(hackathon=hack_select, name="Team Atlas", leader=participants[5])
        team_sel_3 = _get_or_create_team(hackathon=hack_select, name="Team Vector", leader=participants[6])
        _ensure_team_member(team_sel_1, participants[7])
        _ensure_team_member(team_sel_2, participants[8])
        _ensure_team_member(team_sel_3, participants[9])
        # Assign 2 problems; leave others free for selection UI
        if team_sel_1.problem_statement_id is None:
            team_sel_1.problem_statement_id = probs_select[0].id
        if team_sel_2.problem_statement_id is None:
            team_sel_2.problem_statement_id = probs_select[1].id
        db.session.commit()
        _set_team_created_at(team_sel_1.id, now - timedelta(days=4))
        _set_team_created_at(team_sel_2.id, now - timedelta(days=3))
        _set_team_created_at(team_sel_3.id, now - timedelta(days=2))

        # Evaluation hack
        team_eval_1 = _get_or_create_team(hackathon=hack_eval, name="Team Nova", leader=participants[10])
        team_eval_2 = _get_or_create_team(hackathon=hack_eval, name="Team Quantum", leader=participants[11])
        _ensure_team_member(team_eval_1, participants[12])
        _ensure_team_member(team_eval_2, participants[13])
        if team_eval_1.problem_statement_id is None:
            team_eval_1.problem_statement_id = probs_eval[0].id
        if team_eval_2.problem_statement_id is None:
            team_eval_2.problem_statement_id = probs_eval[1].id
        db.session.commit()
        _set_team_created_at(team_eval_1.id, now - timedelta(days=1))
        _set_team_created_at(team_eval_2.id, now - timedelta(days=0))

        # Results-published hack
        team_res_1 = _get_or_create_team(hackathon=hack_results, name="Team Zenith", leader=participants[14])
        if team_res_1.problem_statement_id is None:
            team_res_1.problem_statement_id = probs_results[0].id
        db.session.commit()
        _set_team_created_at(team_res_1.id, now - timedelta(days=6))

        # Ensure solo participants exist for registration-open hack (public + not in any team there)
        # Make a few extra participants public explicitly.
        for p in participants[3:10]:
            # If they are already in teams for other hackathons, that's fine.
            if p.role == UserRole.PARTICIPANT:
                p.is_public = True
        db.session.commit()

        # --- Faculty assignments ---
        for hack in (hack_select, hack_eval, hack_results):
            _ensure_faculty_assignment(hack, faculty1)
            _ensure_faculty_assignment(hack, faculty2)

        # --- Evaluations ---
        _ensure_evaluations(hack_eval, [faculty1, faculty2], [team_eval_1, team_eval_2], live_activity=True)
        _ensure_evaluations(hack_results, [faculty1, faculty2], [team_res_1], live_activity=False)

        # --- Attendance + meal usage ---
        _ensure_attendance(hack_eval, scanned_by=faculty1, participants=participants, count=8)
        _ensure_meal_usage(hack_eval, [team_eval_1, team_eval_2])
        _ensure_meal_usage(hack_open, [team_open_1, team_open_2])

        print("\nDemo data ready.")
        print("Login credentials:")
        print("- Admin:     admin@hackhub.demo / admin123")
        print("- Faculty:   faculty1@hackhub.demo / faculty123")
        print("- Faculty:   faculty2@hackhub.demo / faculty123")
        print("- Participant examples: participant1@hackhub.demo / participant123")


if __name__ == "__main__":
    seed_demo()

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

from sqlalchemy import func, inspect, text

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


RNG = random.Random(20260213)


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
        # Keep existing password_hash; update profile bits.
        # For demo accounts, prefer the spec so repeated seeding keeps data realistic.
        is_demo_account = (spec.email or "").endswith("@hackhub.demo") and (user.email or "").endswith("@hackhub.demo")

        changed = False
        if spec.full_name and (is_demo_account or user.full_name is None):
            if user.full_name != spec.full_name:
                user.full_name = spec.full_name
                changed = True
        if spec.skills and (is_demo_account or user.skills is None):
            if user.skills != spec.skills:
                user.skills = spec.skills
                changed = True
        if spec.experience_level and (is_demo_account or user.experience_level is None):
            if user.experience_level != spec.experience_level:
                user.experience_level = spec.experience_level
                changed = True
        if spec.college and (is_demo_account or user.college is None):
            if user.college != spec.college:
                user.college = spec.college
                changed = True
        if spec.role and user.role != spec.role:
            user.role = spec.role
            changed = True
        if spec.created_at and (is_demo_account or getattr(user, "created_at", None) is None):
            if getattr(user, "created_at", None) != spec.created_at:
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
        cols = inspect(db.engine).get_columns('teams')
        return any(c.get('name') == 'created_at' for c in cols)
    except Exception:
        return False


def _set_team_created_at(team_id: int, created_at: datetime) -> None:
    if not _teams_has_created_at():
        return

    db.session.execute(
        text("UPDATE teams SET created_at = :dt WHERE id = :id"),
        {"dt": created_at, "id": team_id},
    )
    db.session.commit()


def _ensure_problem_statements(hack: Hackathon, app_root: str, count: int = 6) -> list[ProblemStatement]:
    existing = ProblemStatement.query.filter_by(hackathon_id=hack.id).order_by(ProblemStatement.id.asc()).all()
    if len(existing) >= count:
        return existing

    problems: list[ProblemStatement] = list(existing)
    topic_titles = [
        "Smart Queueing for Campus Cafeterias",
        "Energy-Aware Classroom Scheduler",
        "Peer Mentoring Match Platform",
        "Multilingual Student Helpdesk Assistant",
        "Accessible Navigation for New Students",
        "Low-Bandwidth Attendance and Alerts",
        "AI Lab Slot Optimizer",
        "Mental Wellness Early Support Signals",
    ]

    for i in range(len(existing) + 1, count + 1):
        title = f"Challenge {i}: {topic_titles[(i - 1) % len(topic_titles)]}"
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
        RNG.shuffle(faculty_list)
        for evaluator in faculty_list[: min(2, len(faculty_list))]:
            exists = Evaluation.query.filter_by(team_id=team.id, faculty_id=evaluator.id).first()
            if exists:
                continue

            innovation = RNG.randint(6, 10)
            technical = RNG.randint(5, 10)
            uiux = RNG.randint(5, 10)
            practicality = RNG.randint(5, 10)

            total = float(innovation + technical + uiux + practicality)

            created_at = now
            if live_activity:
                # Spread across last 60 minutes to light up the "live" chart.
                minutes_ago = RNG.choice([0, 4, 9, 14, 21, 28, 36, 43, 51, 58])
                created_at = now - timedelta(minutes=minutes_ago)

            if total >= 34:
                comment = "Strong technical depth, clear demo flow, and practical fit for campus rollout."
            elif total >= 29:
                comment = "Good concept and implementation. Could improve polish and edge-case handling."
            else:
                comment = "Promising direction; needs stronger execution and clearer problem validation."

            ev = Evaluation(
                hackathon_id=hack.id,
                team_id=team.id,
                faculty_id=evaluator.id,
                stage_id=1,
                score=total,
                comments=comment,
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
        existing = (
            QRLog.query.filter_by(participant_id=p.id, scan_type="REGISTRATION")
            .filter(func.date(QRLog.timestamp) == event_date)
            .first()
        )

        if not existing:
            checkin_hour = 8 + (p.id % 3)
            checkin_min = (p.id * 7) % 60
            ts = datetime.combine(event_date, datetime.min.time()).replace(
                hour=checkin_hour,
                minute=checkin_min,
                second=0,
                microsecond=0,
            )
            db.session.add(
                QRLog(
                    participant_id=p.id,
                    scanned_by_id=scanned_by.id,
                    scan_type="REGISTRATION",
                    timestamp=ts,
                    details=f"Gate {1 + (p.id % 3)} check-in",
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
            member_count = max(1, len(team.members))
            if mt == "BREAKFAST":
                used_count = max(0, member_count - RNG.randint(1, 2))
            elif mt == "LUNCH":
                used_count = max(0, member_count - RNG.randint(0, 1))
            else:
                used_count = max(0, member_count - RNG.randint(1, 2))

            db.session.add(
                TeamMealUsage(
                    team_id=team.id,
                    meal_type=mt,
                    used_count=used_count,
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

        # Participants spread over last 10 days for registration trends
        participant_specs: list[DemoUserSpec] = []
        profiles = [
            ("Aarav Sharma", "Frontend (React), Tailwind, UI polish", "Intermediate", "NIT Bhopal"),
            ("Ishita Verma", "Backend (Flask), PostgreSQL, API design", "Advanced", "VIT Vellore"),
            ("Rohan Nair", "Data (SQL), analytics dashboards, reporting", "Intermediate", "SRM Institute"),
            ("Meera Kulkarni", "UI/UX (Figma), prototyping, design systems", "Beginner", "MIT-WPU"),
            ("Kabir Singh", "Cloud (AWS), Docker, deployment", "Advanced", "BITS Pilani"),
            ("Ananya Das", "AI/ML (Python), NLP, model evaluation", "Intermediate", "IIIT Delhi"),
            ("Pranav Rao", "Mobile (Flutter), Firebase, app release", "Intermediate", "PES University"),
            ("Sneha Iyer", "Backend (REST), auth, security basics", "Advanced", "Amity University"),
            ("Yash Patil", "Frontend (TypeScript), React, component libraries", "Beginner", "Thapar Institute"),
            ("Diya Menon", "Product, user research, MVP planning", "Intermediate", "Manipal University"),
            ("Aditya Jain", "DevOps, CI/CD, Linux, observability", "Advanced", "Nirma University"),
            ("Ritika Sen", "AI/ML, computer vision, data labeling", "Advanced", "IIT Bhubaneswar"),
            ("Neel Gupta", "Data engineering, ETL, pipelines", "Intermediate", "UPES Dehradun"),
            ("Pooja Arora", "UI/UX, accessibility, UX writing", "Intermediate", "Christ University"),
            ("Arjun Malhotra", "Cybersecurity, secure coding, threat modeling", "Advanced", "LPU Punjab"),
            ("Tanvi Kapoor", "Backend (Django), auth, APIs", "Intermediate", "DTU Delhi"),
            ("Kunal Mehra", "Frontend (Next.js), SEO, performance", "Advanced", "NSUT Delhi"),
            ("Sanya Bose", "Data (Python), visualization, storytelling", "Beginner", "Jadavpur University"),
            ("Harsh Vardhan", "Cloud (GCP), Terraform, infra", "Intermediate", "IIT Mandi"),
            ("Nidhi Sharma", "QA, test automation, reliability", "Intermediate", "IGDTUW"),
            ("Vikram Joshi", "Backend (Java), Spring basics, APIs", "Beginner", "Pune University"),
            ("Ayesha Khan", "UI/UX (Figma), user flows, prototyping", "Advanced", "Jamia Millia Islamia"),
            ("Sahil Bansal", "AI/ML, recommendation systems, Python", "Intermediate", "IIIT Hyderabad"),
            ("Rhea Dutta", "Mobile (Android), Kotlin, offline-first", "Intermediate", "KIIT Bhubaneswar"),
            ("Dev Patel", "Backend (Node.js), queues, caching", "Advanced", "DAIICT Gandhinagar"),
            ("Ira Thomas", "Frontend, accessibility, UI testing", "Intermediate", "St. Xavier's College"),
            ("Manav Sethi", "Security, OWASP, secure APIs", "Intermediate", "Chandigarh University"),
            ("Shreya Pillai", "Data, SQL, metrics, experimentation", "Advanced", "IIM Indore"),
            ("Aman Chopra", "DevOps, Docker, monitoring", "Beginner", "VNIT Nagpur"),
            ("Neha Reddy", "AI/ML, time series, forecasting", "Intermediate", "NIT Warangal"),
            ("Ritesh Gupta", "Backend (Flask), integrations, payments", "Advanced", "IIIT Bangalore"),
            ("Kavya S", "UI/UX, content design, user onboarding", "Beginner", "Anna University"),
            ("Om Prakash", "IoT, sensors, hardware prototyping", "Intermediate", "IIT (Fictional)"),
            ("Pritam Roy", "Frontend (Vue), state management, UI", "Intermediate", "IIEST Shibpur"),
            ("Simran Kaur", "Cloud, Azure, serverless", "Advanced", "GGSIPU"),
            ("Zoya Ali", "Product, stakeholder demos, pitch decks", "Intermediate", "Symbiosis"),
        ]

        for i, (full_name, skills, level, college) in enumerate(profiles, start=1):
            created_at = now - timedelta(days=(i % 10), hours=RNG.randint(0, 23), minutes=RNG.randint(0, 59))
            participant_specs.append(
                DemoUserSpec(
                    username=f"participant{i}",
                    email=f"participant{i}@hackhub.demo",
                    role=UserRole.PARTICIPANT,
                    password="participant123",
                    full_name=full_name,
                    skills=skills,
                    experience_level=level,
                    college=college,
                    is_public=(i % 4 == 0),  # some solo-public participants
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
        # Registration-open hack: multiple teams + plenty of solo participants to discover.
        team_open_1 = _get_or_create_team(hackathon=hack_open, name="Team Aurora", leader=participants[0])
        team_open_2 = _get_or_create_team(hackathon=hack_open, name="Team Nebula", leader=participants[1])
        team_open_3 = _get_or_create_team(hackathon=hack_open, name="Team Beacon", leader=participants[2])
        team_open_4 = _get_or_create_team(hackathon=hack_open, name="Team Orbit", leader=participants[3])

        for p in (participants[4], participants[5], participants[6]):
            _ensure_team_member(team_open_1, p)
        for p in (participants[7], participants[8], participants[9]):
            _ensure_team_member(team_open_2, p)
        for p in (participants[10], participants[11]):
            _ensure_team_member(team_open_3, p)
        for p in (participants[12], participants[13], participants[14]):
            _ensure_team_member(team_open_4, p)

        _set_team_created_at(team_open_1.id, now - timedelta(days=3))
        _set_team_created_at(team_open_2.id, now - timedelta(days=2))
        _set_team_created_at(team_open_3.id, now - timedelta(days=2, hours=3))
        _set_team_created_at(team_open_4.id, now - timedelta(days=1))

        # Problem-selection hack: teams with some problems already picked
        team_sel_1 = _get_or_create_team(hackathon=hack_select, name="Team Prism", leader=participants[15])
        team_sel_2 = _get_or_create_team(hackathon=hack_select, name="Team Atlas", leader=participants[16])
        team_sel_3 = _get_or_create_team(hackathon=hack_select, name="Team Vector", leader=participants[17])
        team_sel_4 = _get_or_create_team(hackathon=hack_select, name="Team Mosaic", leader=participants[18])
        _ensure_team_member(team_sel_1, participants[19])
        _ensure_team_member(team_sel_1, participants[20])
        _ensure_team_member(team_sel_2, participants[21])
        _ensure_team_member(team_sel_3, participants[22])
        _ensure_team_member(team_sel_3, participants[23])
        _ensure_team_member(team_sel_4, participants[24])
        _ensure_team_member(team_sel_4, participants[25])
        # Assign 2 problems; leave others free for selection UI
        if team_sel_1.problem_statement_id is None:
            team_sel_1.problem_statement_id = probs_select[0].id
        if team_sel_2.problem_statement_id is None:
            team_sel_2.problem_statement_id = probs_select[1].id
        db.session.commit()
        _set_team_created_at(team_sel_1.id, now - timedelta(days=5))
        _set_team_created_at(team_sel_2.id, now - timedelta(days=4))
        _set_team_created_at(team_sel_3.id, now - timedelta(days=3))
        _set_team_created_at(team_sel_4.id, now - timedelta(days=2))

        # Evaluation hack
        team_eval_1 = _get_or_create_team(hackathon=hack_eval, name="Team Nova", leader=participants[26])
        team_eval_2 = _get_or_create_team(hackathon=hack_eval, name="Team Quantum", leader=participants[27])
        team_eval_3 = _get_or_create_team(hackathon=hack_eval, name="Team Helix", leader=participants[28])
        team_eval_4 = _get_or_create_team(hackathon=hack_eval, name="Team Lattice", leader=participants[29])
        _ensure_team_member(team_eval_1, participants[30])
        _ensure_team_member(team_eval_1, participants[31])
        _ensure_team_member(team_eval_2, participants[32])
        _ensure_team_member(team_eval_3, participants[33])
        _ensure_team_member(team_eval_4, participants[34])
        _ensure_team_member(team_eval_4, participants[35])
        if team_eval_1.problem_statement_id is None:
            team_eval_1.problem_statement_id = probs_eval[0].id
        if team_eval_2.problem_statement_id is None:
            team_eval_2.problem_statement_id = probs_eval[1].id
        if team_eval_3.problem_statement_id is None:
            team_eval_3.problem_statement_id = probs_eval[2].id
        if team_eval_4.problem_statement_id is None and len(probs_eval) > 3:
            team_eval_4.problem_statement_id = probs_eval[3].id
        db.session.commit()
        _set_team_created_at(team_eval_1.id, now - timedelta(days=1))
        _set_team_created_at(team_eval_2.id, now - timedelta(days=0))
        _set_team_created_at(team_eval_3.id, now - timedelta(hours=10))
        _set_team_created_at(team_eval_4.id, now - timedelta(hours=3))

        # Results-published hack
        team_res_1 = _get_or_create_team(hackathon=hack_results, name="Team Zenith", leader=participants[12])
        team_res_2 = _get_or_create_team(hackathon=hack_results, name="Team Summit", leader=participants[13])
        if team_res_1.problem_statement_id is None:
            team_res_1.problem_statement_id = probs_results[0].id
        if team_res_2.problem_statement_id is None and len(probs_results) > 1:
            team_res_2.problem_statement_id = probs_results[1].id
        db.session.commit()
        _set_team_created_at(team_res_1.id, now - timedelta(days=6))
        _set_team_created_at(team_res_2.id, now - timedelta(days=6, hours=6))

        # Ensure solo participants exist for registration-open hack (public + not in any team there)
        # Make a few extra participants public explicitly.
        for p in participants[8:26]:
            # If they are already in teams for other hackathons, that's fine.
            if p.role == UserRole.PARTICIPANT:
                p.is_public = True
        db.session.commit()

        # --- Faculty assignments ---
        for hack in (hack_select, hack_eval, hack_results):
            _ensure_faculty_assignment(hack, faculty1)
            _ensure_faculty_assignment(hack, faculty2)

        # --- Evaluations ---
        _ensure_evaluations(hack_eval, [faculty1, faculty2], [team_eval_1, team_eval_2, team_eval_3, team_eval_4], live_activity=True)
        _ensure_evaluations(hack_results, [faculty1, faculty2], [team_res_1, team_res_2], live_activity=False)

        # --- Attendance + meal usage ---
        _ensure_attendance(hack_eval, scanned_by=faculty1, participants=participants, count=18)
        _ensure_meal_usage(hack_eval, [team_eval_1, team_eval_2, team_eval_3, team_eval_4])
        _ensure_meal_usage(hack_open, [team_open_1, team_open_2, team_open_3, team_open_4])

        print("\nDemo data ready.")
        print("Login credentials:")
        print("- Admin:     admin@hackhub.demo / admin123")
        print("- Faculty:   faculty1@hackhub.demo / faculty123")
        print("- Faculty:   faculty2@hackhub.demo / faculty123")
        print("- Participant examples: participant1@hackhub.demo / participant123")


if __name__ == "__main__":
    seed_demo()

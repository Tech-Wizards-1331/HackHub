"""Stage-based dummy dataset generator.

Produces realistic, nested hackathon/team/participant data for:
- upcoming
- registration
- topic selection
- coding in progress
- awaiting evaluation
- completed / winners declared

This is *data only* (Python dict / JSON). It does not require DB access.

Usage:
    python stage_dummy_data.py --out instance/stage_dummy_data.json
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


TOPICS: list[str] = [
    "AI / ML",
    "Web Development",
    "Cybersecurity",
    "IoT / Hardware",
    "Cloud / DevOps",
    "FinTech",
    "HealthTech",
    "EdTech",
    "Sustainability",
    "Data Visualization",
]

SKILLS_POOL: list[str] = [
    "Frontend (React)",
    "Backend (Flask)",
    "Backend (Node.js)",
    "Data (SQL)",
    "AI/ML (Python)",
    "UI/UX (Figma)",
    "Cloud (AWS)",
    "Mobile (Flutter)",
]

EXPERIENCE_LEVELS: list[str] = ["Beginner", "Intermediate", "Advanced"]

TEAM_NAME_PARTS_A: list[str] = [
    "Aurora",
    "Nebula",
    "Nova",
    "Quantum",
    "Prism",
    "Atlas",
    "Vector",
    "Zenith",
    "Pulse",
    "Forge",
]

TEAM_NAME_PARTS_B: list[str] = [
    "Labs",
    "Builders",
    "Squad",
    "Collective",
    "Crew",
    "Works",
    "Systems",
    "Studio",
]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick_many(values: list[str], *, k: int) -> str:
    return ", ".join(random.sample(values, k=min(k, len(values))))


def _team_name(i: int) -> str:
    # Stable-ish but still varied
    return f"Team {TEAM_NAME_PARTS_A[i % len(TEAM_NAME_PARTS_A)]} {TEAM_NAME_PARTS_B[(i // 2) % len(TEAM_NAME_PARTS_B)]}"


@dataclass(frozen=True)
class _Participant:
    id: int
    full_name: str
    email: str


def _make_participants(*, start_id: int, count: int) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    for i in range(count):
        pid = start_id + i
        people.append(
            {
                "id": pid,
                "full_name": f"Participant {pid}",
                "email": f"participant{pid}@example.com",
                "skills": _pick_many(SKILLS_POOL, k=2),
                "experience_level": EXPERIENCE_LEVELS[pid % len(EXPERIENCE_LEVELS)],
            }
        )
    return people


def _member_ref(p: dict[str, Any]) -> dict[str, Any]:
    return {"id": p["id"], "full_name": p["full_name"], "email": p["email"]}


def build_stage_dummy_data(*, now: datetime | None = None, seed: int = 1337) -> dict[str, Any]:
    """Return a nested dataset covering all requested hackathon stages."""

    random.seed(seed)

    now = now or datetime.now(timezone.utc)

    # Global pools (shared ids across hackathons for realism)
    participants = _make_participants(start_id=1001, count=28)

    def take_people(n: int, *, offset: int) -> list[dict[str, Any]]:
        return participants[offset : offset + n]

    dataset: dict[str, Any] = {
        "generated_at": _iso(now),
        "topics": list(TOPICS),
        "hackathons": [],
    }

    # 5) Upcoming hackathon
    upcoming_start = now + timedelta(days=14)
    upcoming_end = upcoming_start + timedelta(hours=30)
    dataset["hackathons"].append(
        {
            "id": 501,
            "name": "Campus Innovation Hackathon 2026 (Upcoming)",
            "status": "upcoming",
            "db_status": "DRAFT",
            "description": "A 30-hour hackathon focused on building practical campus tools.",
            "rules": [
                "Teams of 1–4 participants",
                "All code must be written during the hackathon window",
                "Use of open-source libraries is allowed",
                "Submit before the deadline to be evaluated",
            ],
            "timeline": {
                "registration_opens": _iso(now + timedelta(days=7)),
                "registration_closes": _iso(now + timedelta(days=13, hours=12)),
                "topic_selection_deadline": _iso(upcoming_start + timedelta(hours=2)),
                "coding_starts": _iso(upcoming_start),
                "submission_deadline": _iso(upcoming_end - timedelta(hours=2)),
                "ends": _iso(upcoming_end),
            },
            "available_topics": random.sample(TOPICS, k=7),
            "teams": [],
            "participants": take_people(8, offset=0),
        }
    )

    # 4) Registration phase
    reg_start = now - timedelta(days=1)
    reg_end = now + timedelta(days=2)
    reg_participants = take_people(14, offset=5)
    dataset["hackathons"].append(
        {
            "id": 502,
            "name": "Campus Innovation Hackathon 2026 (Registration Open)",
            "status": "registration_open",
            "db_status": "REGISTRATION_OPEN",
            "description": "Registrations are open. Participants can form teams or opt to be discoverable.",
            "timeline": {
                "registration_opens": _iso(reg_start),
                "registration_closes": _iso(now + timedelta(days=2)),
                "starts": _iso(now + timedelta(days=3)),
                "ends": _iso(now + timedelta(days=4, hours=6)),
            },
            "participants": [
                {
                    **p,
                    "team_preference": random.choice(["looking_for_team", "wants_to_create_team", "already_in_team"]),
                    "is_visible_to_team_leaders": random.choice([True, False, False]),
                }
                for p in reg_participants
            ],
            "teams": [
                {
                    "id": 9001,
                    "name": _team_name(1),
                    "topic": None,
                    "status": "forming",
                    "members": [_member_ref(reg_participants[0]), _member_ref(reg_participants[1])],
                    "leader_id": reg_participants[0]["id"],
                },
                {
                    "id": 9002,
                    "name": _team_name(2),
                    "topic": None,
                    "status": "forming",
                    "members": [_member_ref(reg_participants[2])],
                    "leader_id": reg_participants[2]["id"],
                },
            ],
        }
    )

    # 3) Topic selection phase
    select_start = now - timedelta(days=4)
    select_end = now + timedelta(days=1)
    select_participants = take_people(12, offset=12)
    topics_for_select = random.sample(TOPICS, k=6)

    def topic_or_pending(i: int) -> str | None:
        return topics_for_select[i % len(topics_for_select)] if i % 3 != 0 else None

    dataset["hackathons"].append(
        {
            "id": 503,
            "name": "Campus Innovation Hackathon 2026 (Topic Selection)",
            "status": "topic_selection",
            "db_status": "PROBLEM_SELECTION",
            "description": "Registrations closed. Teams are selecting topics from the official list.",
            "timeline": {
                "registration_closes": _iso(select_start + timedelta(hours=12)),
                "topic_selection_opens": _iso(select_start + timedelta(days=1)),
                "topic_selection_deadline": _iso(now + timedelta(hours=18)),
                "starts": _iso(now + timedelta(days=1)),
                "ends": _iso(select_end + timedelta(days=2)),
            },
            "available_topics": topics_for_select,
            "participants": select_participants,
            "teams": [
                {
                    "id": 9100 + i,
                    "name": _team_name(10 + i),
                    "topic": topic_or_pending(i),
                    "status": "selecting_topic" if topic_or_pending(i) is None else "topic_selected",
                    "members": [_member_ref(select_participants[(i * 3) % len(select_participants)])],
                    "leader_id": select_participants[(i * 3) % len(select_participants)]["id"],
                }
                for i in range(4)
            ],
        }
    )

    # 6) Ongoing hackathon (coding in progress)
    ongoing_start = now - timedelta(hours=3)
    ongoing_end = now + timedelta(hours=22)
    ongoing_participants = take_people(12, offset=2)
    ongoing_topics = random.sample(TOPICS, k=5)

    dataset["hackathons"].append(
        {
            "id": 504,
            "name": "Campus Innovation Hackathon 2026 (Ongoing)",
            "status": "coding_in_progress",
            "db_status": "ONGOING",
            "description": "Hackathon is live. Teams are coding and faculty can see live progress.",
            "timeline": {
                "starts": _iso(ongoing_start),
                "submission_deadline": _iso(ongoing_end - timedelta(hours=2)),
                "ends": _iso(ongoing_end),
            },
            "teams": [
                {
                    "id": 9201,
                    "name": _team_name(21),
                    "topic": ongoing_topics[0],
                    "status": "coding_in_progress",
                    "members": [_member_ref(ongoing_participants[0]), _member_ref(ongoing_participants[1]), _member_ref(ongoing_participants[2])],
                    "leader_id": ongoing_participants[0]["id"],
                    "progress": {
                        "last_update": _iso(now - timedelta(minutes=25)),
                        "completion_percent": 55,
                        "notes": "Core backend APIs working; polishing UI and demo script.",
                        "partial_submission": {
                            "submitted": True,
                            "repo_url": "https://example.com/repo/team-aurora",
                            "demo_url": None,
                        },
                    },
                },
                {
                    "id": 9202,
                    "name": _team_name(22),
                    "topic": ongoing_topics[1],
                    "status": "coding_in_progress",
                    "members": [_member_ref(ongoing_participants[3]), _member_ref(ongoing_participants[4])],
                    "leader_id": ongoing_participants[3]["id"],
                    "progress": {
                        "last_update": _iso(now - timedelta(minutes=10)),
                        "completion_percent": 30,
                        "notes": "Initial prototype + data model done; integrating auth flows.",
                        "partial_submission": {
                            "submitted": False,
                            "repo_url": None,
                            "demo_url": None,
                        },
                    },
                },
            ],
            "participants": ongoing_participants,
        }
    )

    # 2) Coding phase completed; evaluations pending
    coding_end = now - timedelta(hours=8)
    awaiting_eval_start = now - timedelta(days=2)
    awaiting_eval_end = now - timedelta(hours=6)
    awaiting_participants = take_people(14, offset=8)

    dataset["hackathons"].append(
        {
            "id": 505,
            "name": "Campus Innovation Hackathon 2026 (Awaiting Evaluation)",
            "status": "awaiting_evaluation",
            "db_status": "EVALUATION",
            "description": "Coding window ended. Teams have submitted and are waiting for faculty scoring.",
            "timeline": {
                "starts": _iso(awaiting_eval_start),
                "coding_ends": _iso(coding_end),
                "submission_deadline": _iso(awaiting_eval_end),
                "evaluation_starts": _iso(now + timedelta(hours=2)),
                "ends": _iso(awaiting_eval_end),
            },
            "teams": [
                {
                    "id": 9301 + i,
                    "name": _team_name(31 + i),
                    "topic": random.choice(TOPICS),
                    "status": "submitted",
                    "submission": {
                        "submitted_at": _iso(awaiting_eval_end - timedelta(minutes=20 + i * 13)),
                        "repo_url": f"https://example.com/repo/team-{9301+i}",
                        "demo_url": f"https://demo.example.com/team-{9301+i}",
                        "notes": "Final build uploaded; ready for judging.",
                    },
                    "members": [
                        _member_ref(awaiting_participants[(i * 3) % len(awaiting_participants)]),
                        _member_ref(awaiting_participants[(i * 3 + 1) % len(awaiting_participants)]),
                        _member_ref(awaiting_participants[(i * 3 + 2) % len(awaiting_participants)]),
                    ],
                    "leader_id": awaiting_participants[(i * 3) % len(awaiting_participants)]["id"],
                    "scores": None,
                    "final_result": None,
                }
                for i in range(3)
            ],
            "participants": awaiting_participants,
        }
    )

    # 1) Hackathon completed; evaluations done; winners declared
    completed_start = now - timedelta(days=12)
    completed_end = completed_start + timedelta(hours=30)
    completed_participants = take_people(18, offset=0)

    teams_completed: list[dict[str, Any]] = []
    base_team_id = 9401
    for i in range(random.randint(3, 5)):
        members = [
            _member_ref(completed_participants[(i * 4) % len(completed_participants)]),
            _member_ref(completed_participants[(i * 4 + 1) % len(completed_participants)]),
            _member_ref(completed_participants[(i * 4 + 2) % len(completed_participants)]),
        ]

        scores = {
            "innovation": random.randint(6, 10),
            "technical": random.randint(6, 10),
            "uiux": random.randint(5, 10),
            "practicality": random.randint(5, 10),
        }
        total = float(sum(scores.values()))

        teams_completed.append(
            {
                "id": base_team_id + i,
                "name": _team_name(41 + i),
                "topic": random.choice(TOPICS),
                "status": "winner_declared",
                "members": members,
                "leader_id": members[0]["id"],
                "submission": {
                    "submitted_at": _iso(completed_end - timedelta(hours=2, minutes=15 + i * 7)),
                    "repo_url": f"https://example.com/repo/completed-{base_team_id+i}",
                    "demo_url": f"https://demo.example.com/completed-{base_team_id+i}",
                },
                "scores": {**scores, "total": total},
                "final_result": None,  # filled after ranking
                "is_winner": False,
            }
        )

    # Rank by total score
    teams_completed.sort(key=lambda t: t["scores"]["total"], reverse=True)
    for rank, t in enumerate(teams_completed, start=1):
        t["final_result"] = {"placement": rank, "label": "Winner" if rank == 1 else "Runner-up" if rank == 2 else "Finalist"}
        t["is_winner"] = rank in (1, 2)  # 1st + 2nd as winners

    dataset["hackathons"].append(
        {
            "id": 506,
            "name": "Campus Innovation Hackathon 2026 (Completed)",
            "status": "winner_declared",
            "db_status": "RESULT_PUBLISHED",
            "description": "Evaluations completed and winners published.",
            "timeline": {
                "starts": _iso(completed_start),
                "submission_deadline": _iso(completed_end - timedelta(hours=2)),
                "ends": _iso(completed_end),
                "results_published": _iso(completed_end + timedelta(days=1)),
            },
            "teams": teams_completed,
            "participants": completed_participants,
            "winners": [
                {"team_id": t["id"], "team_name": t["name"], "placement": t["final_result"]["placement"], "score": t["scores"]["total"]}
                for t in teams_completed
                if t["is_winner"]
            ],
            "evaluations_done": True,
        }
    )

    return dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate stage-based dummy hackathon dataset (JSON)")
    parser.add_argument("--out", default="instance/stage_dummy_data.json", help="Output JSON file path")
    parser.add_argument("--seed", type=int, default=1337, help="Random seed")
    args = parser.parse_args()

    data = build_stage_dummy_data(seed=args.seed)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

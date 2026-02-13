"""Upgrade the local database schema without starting the web server.

This project uses SQLAlchemy's `create_all()` plus a lightweight SQLite-only
schema upgrade step inside `app.create_app()`.

Why this exists:
- `db.create_all()` will NOT add new columns to existing tables.
- Existing SQLite DB files may miss newer columns (e.g. hackathons.breakfast_time).

Usage (PowerShell):
  & ./.venv/Scripts/python.exe ./HackHub/upgrade_db_schema.py
  $env:DATABASE_URL = "sqlite:///C:/path/to/other.db"; & ./.venv/Scripts/python.exe ./HackHub/upgrade_db_schema.py
"""

from __future__ import annotations

import argparse

from sqlalchemy import text


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HackHub DB schema upgrade (no server).")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print errors (no success message).",
    )
    args = parser.parse_args()

    # Import here so running this script doesn't require Flask env vars upfront.
    from app import create_app  # pylint: disable=import-error
    from app.extensions import db  # pylint: disable=import-error

    app = create_app()

    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(users)")).all()]
            if "contact" in cols:
                try:
                    db.session.execute(text("ALTER TABLE users DROP COLUMN contact"))
                    db.session.commit()
                    if not args.quiet:
                        print("Removed users.contact column.")
                except Exception as exc:
                    db.session.rollback()
                    if not args.quiet:
                        print(f"Warning: could not drop users.contact column: {exc}")
        elif not args.quiet:
            print("Note: Non-SQLite DB detected. Use your migration tool to drop users.contact.")

    if not args.quiet:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        print("DB schema upgrade completed.")
        print(f"SQLALCHEMY_DATABASE_URI: {uri}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

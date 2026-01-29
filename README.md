# HackHub

## Local DB schema upgrade (SQLite)

If you pull new code and hit errors like `no such column: hackathons.breakfast_time`, your existing `instance/hackhub.db` is older than the current models.

Run:

`& .\.venv\Scripts\python.exe .\HackHub\upgrade_db_schema.py`
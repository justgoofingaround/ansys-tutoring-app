"""SQLite access: one connection per request (FastAPI dependency closes it).

Raw sqlite3, no ORM — matches the project convention (the sibling repo's
event_logger.py is raw sqlite3) and the ~30-user single-writer deployment.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Migrations for columns added after a deployment's DB was created —
        # executescript's CREATE TABLE IF NOT EXISTS won't touch existing
        # tables. Idempotent; runs on every boot.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tutorials)")}
        if "report_guidelines" not in cols:
            conn.execute("ALTER TABLE tutorials ADD COLUMN report_guidelines TEXT")
        conn.commit()
    finally:
        conn.close()

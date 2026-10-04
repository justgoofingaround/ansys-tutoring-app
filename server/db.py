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
        # Roster-based registration: existing deployments get the columns on the
        # next boot. SQLite cannot add a UNIQUE column via ALTER, so uniqueness
        # for migrated databases comes from the index below (the CREATE TABLE
        # above already carries it for fresh ones).
        user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "email" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "email_verified_at" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified_at REAL")
        if "email_verified_by" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified_by INTEGER")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email"
            " ON users (email COLLATE NOCASE) WHERE email IS NOT NULL"
        )
        conn.commit()
    finally:
        conn.close()

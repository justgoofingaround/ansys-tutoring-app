"""Event ingestion — the overlay contract (POST /events/{table}, batched).

Anti-spoof: whatever session_token the payload carries is OVERWRITTEN with
the authenticated caller's opaque token, so one student can never write
another student's history.
"""

import json
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import current_user, get_db
from ..models import ActionEventIn

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/action_events", status_code=202)
def ingest_action_events(
    events: list[ActionEventIn],
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    token = user["opaque_token"]
    if not token:
        raise HTTPException(status_code=403, detail="students_only")
    now = time.time()
    conn.executemany(
        """INSERT INTO action_events
           (session_token, tutorial_id, step_id, action_type, uia_automation_id,
            timestamp, extra, received_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (
                token, e.tutorial_id, e.step_id, e.action_type,
                e.uia_automation_id, e.timestamp, json.dumps(e.extra), now,
            )
            for e in events
        ],
    )
    conn.commit()
    return {"accepted": len(events)}

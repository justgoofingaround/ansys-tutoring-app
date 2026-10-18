"""The checker on the instructor desktop talks to the hub through here.

Why this exists: the hub runs on a VM with no GPU, while the machine that can
actually run the rubric — and the AI review — is the instructor's desktop. So
the hub takes custody of an uploaded report and a checker on that desktop
claims the work, runs it there, and posts the result back.

The hub never calls the desktop. The desktop polls, which means it needs no
inbound firewall rule, no fixed address and no certificate, and it can be
closed or rebooted mid-lab without the hub noticing anything worse than a
queue that stops draining.

Auth is a shared secret in X-Agent-Token (AGENT_TOKEN), compared in constant
time. With no token configured every route here refuses: an unconfigured hub
must not expose student work to an unauthenticated caller.
"""

import hmac
import json
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse

from ..config import Settings
from ..deps import get_db, get_settings
from ..models import ReportResultIn
from ..services import tutorial_store

router = APIRouter(prefix="/api/agent", tags=["agent"])

# A claim older than this is assumed dead — the desktop was closed or crashed
# mid-check — and the submission goes back in the queue.
CLAIM_TIMEOUT_S = 15 * 60


def require_agent(
    x_agent_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.agent_token
    if not expected or not x_agent_token or not hmac.compare_digest(x_agent_token, expected):
        raise HTTPException(status_code=401, detail="bad_agent_token")


@router.post("/reports/claim", dependencies=[Depends(require_agent)])
def claim_report(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Hand the oldest waiting submission to the caller, or {} if none.

    Claiming is a single UPDATE guarded by the current status, so two checkers
    racing cannot both win the same row: the loser updates zero rows.
    """
    now = time.time()
    conn.execute(
        """UPDATE report_submissions SET status = 'pending', claimed_at = NULL
           WHERE status = 'claimed' AND claimed_at < ?""",
        (now - CLAIM_TIMEOUT_S,),
    )
    row = conn.execute(
        """SELECT * FROM report_submissions WHERE status = 'pending'
           ORDER BY submitted_at LIMIT 1"""
    ).fetchone()
    if row is None:
        conn.commit()
        return {}

    cur = conn.execute(
        """UPDATE report_submissions SET status = 'claimed', claimed_at = ?
           WHERE id = ? AND status = 'pending'""",
        (now, row["id"]),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {}  # another checker took it between the select and the update

    found = tutorial_store.get_published(conn, row["tutorial_id"])
    content, meta = found if found else ({}, {"report_guidelines": None})
    return {
        "submission_id": row["id"],
        "tutorial_id": row["tutorial_id"],
        "filename": row["filename"],
        # The rubric travels with the work, so the desktop needs no copy of
        # the tutorial content and cannot check against a stale version.
        "report_checks": content.get("report_checks", {}),
        "guidelines": meta["report_guidelines"] if meta else None,
        "submitted_at": row["submitted_at"],
        # ENABLE_AI lives on the hub, but the model runs on the desktop. Send
        # the switch with the job so one master switch still means one master
        # switch across the machine boundary.
        "ai_enabled": settings.enable_ai,
    }


@router.get("/reports/{submission_id}/file", dependencies=[Depends(require_agent)])
def download_report(submission_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        "SELECT stored_path, filename FROM report_submissions WHERE id = ?", (submission_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="submission_not_found")
    path = Path(row["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="file_missing")
    return FileResponse(path, filename=row["filename"])


@router.post("/reports/{submission_id}/result", dependencies=[Depends(require_agent)])
def post_result(
    submission_id: int,
    body: ReportResultIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Record what the desktop decided. Idempotent: re-posting the same result
    is harmless, which matters because the checker retries after a dropped
    connection without knowing whether the first attempt landed."""
    row = conn.execute(
        "SELECT id FROM report_submissions WHERE id = ?", (submission_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="submission_not_found")

    conn.execute(
        """UPDATE report_submissions
           SET ok = ?, score = ?, total = ?, checks = ?, feedback = ?,
               llm_review = ?, status = ?, checked_at = ?, claimed_at = NULL
           WHERE id = ?""",
        (
            int(body.ok), body.score, body.total,
            json.dumps([c.model_dump() for c in body.checks]), body.feedback,
            json.dumps(body.llm_review) if body.llm_review is not None else None,
            "failed" if body.failed else "checked", time.time(), submission_id,
        ),
    )
    conn.commit()
    return {"submission_id": submission_id, "status": "failed" if body.failed else "checked"}


@router.get("/status")
def agent_status(conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Queue depth and when a checker was last heard from.

    Deliberately open to any signed-in caller — it carries no student data,
    and the instructor page needs it to say whether the desktop checker is
    running. The hub cannot ping the desktop, so "last seen" is the most
    honest signal available.
    """
    row = conn.execute(
        """SELECT
             SUM(status = 'pending') AS pending,
             SUM(status = 'claimed') AS in_progress,
             SUM(status = 'failed') AS failed,
             MAX(claimed_at) AS last_claim,
             MAX(checked_at) AS last_result
           FROM report_submissions"""
    ).fetchone()
    last_seen = max(row["last_claim"] or 0, row["last_result"] or 0) or None
    return {
        "pending": row["pending"] or 0,
        "in_progress": row["in_progress"] or 0,
        "failed": row["failed"] or 0,
        "checker_last_seen": last_seen,
    }

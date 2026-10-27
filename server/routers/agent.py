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
from ..deps import get_db, get_settings, require_instructor
from ..models import ReportResultIn
from ..services import report_listing, tutorial_store

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

    return _job(conn, row, settings)


def _job(conn: sqlite3.Connection, row: sqlite3.Row, settings: Settings) -> dict:
    """What a checker needs to grade one submission, and nothing else."""
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
        # The model runs on the desktop, but the hub decides whether it may:
        # the switch travels with the job. ENABLE_REPORT_AI covers exactly
        # this, without turning on the AI features the hub itself serves.
        "ai_enabled": settings.report_ai_allowed,
    }


@router.post("/reports/{submission_id}/claim", dependencies=[Depends(require_agent)])
def claim_one(
    submission_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Claim one named submission, including one already checked.

    The queue hands out the oldest waiting report, which is right for a
    checker running unattended. The grading app is the other case: the
    instructor points at a report and asks for it to be looked at again,
    usually because it was graded while no model was available. Re-claiming
    a checked report is therefore allowed and is what "run the AI review"
    means; the rubric is deterministic, so it simply produces the same score
    again alongside the new review.
    """
    row = conn.execute(
        "SELECT * FROM report_submissions WHERE id = ?", (submission_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="submission_not_found")
    if not Path(row["stored_path"]).is_file():
        raise HTTPException(status_code=410, detail="file_missing")
    conn.execute(
        "UPDATE report_submissions SET status = 'claimed', claimed_at = ? WHERE id = ?",
        (time.time(), submission_id),
    )
    conn.commit()
    return _job(conn, row, settings)


@router.get("/config", dependencies=[Depends(require_agent)])
def agent_config(settings: Settings = Depends(get_settings)) -> dict:
    """What the hub permits, so the grading app can say so before he clicks.

    The AI switch lives on the hub; a desktop with a GPU does not get to
    decide. Without this the app would only find out by trying, and the
    instructor would read a failure where he deserved a greyed-out button.
    """
    return {"ai_enabled": settings.report_ai_allowed}


@router.get("/reports", dependencies=[Depends(require_agent)])
def list_reports_for_agent(
    status: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    """The same list the instructor dashboard shows, for the grading app.

    This is the one place the agent token sees student names. It is granted
    because the app it serves is a gradebook on the instructor's own desktop,
    and grading an anonymous queue is not grading. It widens what a leaked
    token gives: before, files and opaque tokens; now, names as well. The
    token therefore belongs on that machine and nowhere else.

    `status=no_ai` is the one the app leans on: checked by the rubric, with
    no model review attached.
    """
    return report_listing.list_submissions(conn, status=status)


@router.post("/reports/{submission_id}/feedback", dependencies=[Depends(require_agent)])
def agent_leave_feedback(
    submission_id: int, body: dict, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    """Write the instructor's note from the desktop app rather than the browser.

    Same column, same student-visible result as the dashboard's feedback box.
    No CSRF dependency here: this is a token-authenticated API call from a
    local app, not a cookie-authenticated form a third-party page could forge.
    """
    text = (body.get("feedback") or "").strip()
    if len(text) > report_listing.MAX_FEEDBACK_CHARS:
        raise HTTPException(status_code=422, detail="feedback_too_long")
    result = report_listing.set_feedback(conn, submission_id, text)
    if result is None:
        raise HTTPException(status_code=404, detail="submission_not_found")
    return result


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
def agent_status(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_instructor),
) -> dict:
    """Queue depth and when a checker was last heard from.

    Instructor-only: the Reports page needs it to say whether the desktop
    checker is running, and it tells a student nothing they can act on. The
    hub cannot ping the desktop, so "last seen" is the most honest signal
    available. This is the one route here a browser calls, so it takes a
    session rather than the agent token; the checker never asks for it.
    """
    row = conn.execute(
        """SELECT
             SUM(status = 'pending') AS pending,
             SUM(status = 'claimed') AS in_progress,
             SUM(status = 'failed') AS failed,
             SUM((status = 'failed' OR (status = 'checked' AND ok = 0))
                 AND instructor_feedback IS NULL) AS needs_review,
             MAX(claimed_at) AS last_claim,
             MAX(checked_at) AS last_result
           FROM report_submissions"""
    ).fetchone()
    last_seen = max(row["last_claim"] or 0, row["last_result"] or 0) or None
    return {
        "pending": row["pending"] or 0,
        "in_progress": row["in_progress"] or 0,
        "failed": row["failed"] or 0,
        # Reports the rubric could not pass and nobody has written back about.
        # A passing report needs no one, so counting those would leave a badge
        # the instructor can never clear.
        "needs_review": row["needs_review"] or 0,
        "checker_last_seen": last_seen,
        # The page decides "the checker is down" from how old last_seen is, so
        # it needs our clock, not the browser's.
        "now": time.time(),
    }

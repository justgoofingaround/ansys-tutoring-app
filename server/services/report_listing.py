"""Listing and annotating report submissions, for the two callers that do it.

The instructor dashboard reads this over a browser session; the grading app
on the instructor's desktop reads the same thing over the agent token. They
must show the same submission the same way, so the query lives here rather
than in whichever router grew it first.

The student's name is joined in here. That join is deliberate and narrow:
the activity tables store only opaque tokens, and a gradebook is one of the
few places a name belongs. See server/schema.sql's header.
"""

import json
import sqlite3
import time

MAX_FEEDBACK_CHARS = 4000


def list_submissions(
    conn: sqlite3.Connection,
    status: str | None = None,
    tutorial_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Every submission, newest first, with the student's name attached.

    The stored path is deliberately not returned — the download routes are
    the only way to a file, so no caller can leak a filesystem path.
    """
    sql = """SELECT r.id, r.session_token, r.tutorial_id, r.tutorial_version,
                    r.filename, r.ok, r.score, r.total, r.checks, r.feedback,
                    r.llm_review, r.submitted_at, r.status, r.checked_at,
                    r.instructor_feedback, r.instructor_feedback_at,
                    u.username, s.name AS section, t.title AS tutorial_title
             FROM report_submissions r
             LEFT JOIN users u ON u.opaque_token = r.session_token
             LEFT JOIN sections s ON s.id = u.section_id
             LEFT JOIN tutorials t ON t.tutorial_id = r.tutorial_id"""
    where: list[str] = []
    args: list = []
    if status == "queued":
        # Waiting plus in-flight: a report a checker is working on right now
        # is still something the instructor is waiting for.
        where.append("r.status IN ('pending', 'claimed')")
    elif status == "no_ai":
        # Checked, but the model never ran — graded while Ollama was off, or
        # before it was installed. The rubric stands; the review is missing.
        where.append(
            "r.status = 'checked' AND (r.llm_review IS NULL"
            " OR json_extract(r.llm_review, '$.available') IS NOT 1)"
        )
    elif status:
        where.append("r.status = ?")
        args.append(status)
    if tutorial_id:
        where.append("r.tutorial_id = ?")
        args.append(tutorial_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.submitted_at DESC LIMIT ?"
    args.append(limit)

    return [
        {
            "submission_id": r["id"],
            # The student may have been removed; the work stays, anonymous.
            "student": r["username"] or "(removed account)",
            "section": r["section"],
            "tutorial_id": r["tutorial_id"],
            "tutorial_title": r["tutorial_title"] or r["tutorial_id"],
            "tutorial_version": r["tutorial_version"],
            "filename": r["filename"],
            "status": r["status"],
            "ok": bool(r["ok"]),
            "score": r["score"],
            "total": r["total"],
            "checks": json.loads(r["checks"]) if r["checks"] else [],
            "feedback": r["feedback"],
            "llm_review": json.loads(r["llm_review"]) if r["llm_review"] else None,
            "submitted_at": r["submitted_at"],
            "checked_at": r["checked_at"],
            "instructor_feedback": r["instructor_feedback"],
            "instructor_feedback_at": r["instructor_feedback_at"],
        }
        for r in conn.execute(sql, args).fetchall()
    ]


def set_feedback(conn: sqlite3.Connection, submission_id: int, text: str) -> dict | None:
    """Write the instructor's note about one submission; None if it is gone.

    The rubric says whether the required pieces are present; it cannot say
    "your mesh is too coarse near the fillet". This is where that goes, and
    the student sees it on the tutorial page. Empty text clears the note.
    """
    text = (text or "").strip()
    row = conn.execute(
        "SELECT id FROM report_submissions WHERE id = ?", (submission_id,)
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        """UPDATE report_submissions
           SET instructor_feedback = ?, instructor_feedback_at = ?
           WHERE id = ?""",
        (text or None, time.time() if text else None, submission_id),
    )
    conn.commit()
    return {"submission_id": submission_id, "instructor_feedback": text or None}

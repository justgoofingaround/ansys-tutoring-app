"""Progress derivation — computed on read (cohort <= 30, no caching).

Step status for a token, from action_events:
  completed   a step_completed event exists
  struggling  >= 3 verify_failed events (and not completed)
  attempted   any event
  not_started otherwise

Tutorial status is a milestone lattice that stays meaningful while the
desktop overlay isn't sending events yet (day one, the only signals are
web-generated: report uploads and quiz submissions):
  completed    every milestone that EXISTS is met — report ok (if the
               tutorial has report_checks), quiz submitted (if a published
               quiz exists); if neither exists, all runtime steps completed
  in_progress  any event / submission at all
  not_started  nothing

percent: with step events -> 70% steps + 15% quiz + 15% report (weights of
missing milestones fold into steps); without events -> coarse 0/50/100.
"""

import sqlite3

from . import tutorial_store

STRUGGLE_THRESHOLD = 3


def step_statuses(
    conn: sqlite3.Connection, token: str, tutorial_id: str, step_ids: list[str]
) -> dict[str, dict]:
    rows = conn.execute(
        """SELECT step_id, action_type, COUNT(*) AS n FROM action_events
           WHERE session_token = ? AND tutorial_id = ?
           GROUP BY step_id, action_type""",
        (token, tutorial_id),
    ).fetchall()
    by_step: dict[str, dict] = {}
    for r in rows:
        agg = by_step.setdefault(r["step_id"], {"completed": False, "fails": 0, "events": 0})
        agg["events"] += r["n"]
        if r["action_type"] == "step_completed":
            agg["completed"] = True
        elif r["action_type"] == "verify_failed":
            agg["fails"] += r["n"]

    out = {}
    for sid in step_ids:
        agg = by_step.get(sid)
        if agg is None:
            status = "not_started"
            fails = 0
        elif agg["completed"]:
            status, fails = "completed", agg["fails"]
        elif agg["fails"] >= STRUGGLE_THRESHOLD:
            status, fails = "struggling", agg["fails"]
        else:
            status, fails = "attempted", agg["fails"]
        out[sid] = {"status": status, "fail_count": fails}
    return out


def _report_state(conn: sqlite3.Connection, token: str, tutorial_id: str) -> dict | None:
    row = conn.execute(
        """SELECT ok, score, total, submitted_at FROM report_submissions
           WHERE session_token = ? AND tutorial_id = ?
           ORDER BY submitted_at DESC LIMIT 1""",
        (token, tutorial_id),
    ).fetchone()
    if row is None:
        return None
    any_ok = conn.execute(
        """SELECT 1 FROM report_submissions
           WHERE session_token = ? AND tutorial_id = ? AND ok = 1 LIMIT 1""",
        (token, tutorial_id),
    ).fetchone()
    return {
        "ok": bool(any_ok),
        "last_score": row["score"],
        "last_total": row["total"],
        "submitted_at": row["submitted_at"],
    }


def _quiz_state(conn: sqlite3.Connection, token: str, tutorial_id: str) -> dict | None:
    # The tutorial's ACTIVE quiz is the one tutorials.quiz_id points at —
    # scanning quizzes by tutorial_id would pick arbitrarily when a quiz
    # has been replaced by a new upload.
    quiz = conn.execute(
        """SELECT q.quiz_id FROM tutorials t JOIN quizzes q ON q.quiz_id = t.quiz_id
           WHERE t.tutorial_id = ? AND q.is_published = 1""",
        (tutorial_id,),
    ).fetchone()
    if quiz is None:
        return None
    row = conn.execute(
        """SELECT MAX(score) AS best, COUNT(*) AS attempts FROM quiz_submissions
           WHERE session_token = ? AND quiz_id = ?""",
        (token, quiz["quiz_id"]),
    ).fetchone()
    return {
        "quiz_id": quiz["quiz_id"],
        "best_score": row["best"],
        "attempts": row["attempts"] or 0,
    }


def tutorial_summary(
    conn: sqlite3.Connection, token: str, tutorial_id: str, content: dict
) -> dict:
    step_ids = tutorial_store.runtime_step_ids(content)
    steps = step_statuses(conn, token, tutorial_id, step_ids)
    completed = sum(1 for s in steps.values() if s["status"] == "completed")
    has_events = any(s["status"] != "not_started" for s in steps.values())

    report = _report_state(conn, token, tutorial_id)
    quiz = _quiz_state(conn, token, tutorial_id)
    needs_report = bool(content.get("report_checks"))
    report_ok = bool(report and report["ok"])
    quiz_done = bool(quiz and quiz["attempts"] > 0)

    # Milestones that exist for this tutorial
    milestones: list[bool] = []
    if needs_report:
        milestones.append(report_ok)
    if quiz is not None:
        milestones.append(quiz_done)

    if milestones:
        done = all(milestones)
    else:
        done = bool(step_ids) and completed == len(step_ids)

    any_activity = has_events or report is not None or quiz_done
    status = "completed" if done else ("in_progress" if any_activity else "not_started")

    if has_events and step_ids:
        w_quiz = 0.15 if quiz is not None else 0.0
        w_report = 0.15 if needs_report else 0.0
        w_steps = 1.0 - w_quiz - w_report
        percent = (
            w_steps * (completed / len(step_ids))
            + w_quiz * (1.0 if quiz_done else 0.0)
            + w_report * (1.0 if report_ok else 0.0)
        )
        percent = round(percent * 100)
    else:
        percent = 100 if done else (50 if any_activity else 0)

    current = next(
        (sid for sid in step_ids if steps[sid]["status"] != "completed"), None
    )
    return {
        "tutorial_id": tutorial_id,
        "status": status,
        "percent": percent,
        "steps_total": len(step_ids),
        "steps_completed": completed,
        "current_step_id": current if status != "completed" else None,
        "report": report if needs_report else None,
        "needs_report": needs_report,
        "quiz": quiz,
        "step_statuses": steps,
    }

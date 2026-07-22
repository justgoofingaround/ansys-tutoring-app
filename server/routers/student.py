"""Student-facing aggregate views: dashboard + per-tutorial detail."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, require_student
from ..services import progress, tutorial_store

router = APIRouter(prefix="/api/student", tags=["student"])


@router.get("/dashboard")
def dashboard(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    token = user["opaque_token"]
    tutorials = []
    cont = None
    for entry in tutorial_store.list_published(conn):
        found = tutorial_store.get_published(conn, entry["tutorial_id"])
        if not found:
            continue
        content, _ = found
        summary = progress.tutorial_summary(conn, token, entry["tutorial_id"], content)
        card = {
            **entry,
            "status": summary["status"],
            "percent": summary["percent"],
            "steps_total": summary["steps_total"],
            "steps_completed": summary["steps_completed"],
            "current_step_id": summary["current_step_id"],
            "report": summary["report"],
            "needs_report": summary["needs_report"],
            "quiz": summary["quiz"],
        }
        tutorials.append(card)
        if cont is None and summary["status"] == "in_progress":
            step_title = None
            if summary["current_step_id"]:
                for sec in content.get("sections", []):
                    for st in sec.get("steps", []):
                        if st.get("step_id") == summary["current_step_id"]:
                            step_title = st.get("title")
            cont = {
                "tutorial_id": entry["tutorial_id"],
                "title": entry["title"],
                "step_id": summary["current_step_id"],
                "step_title": step_title,
            }
    return {"tutorials": tutorials, "continue": cont}


@router.get("/tutorials/{tutorial_id}")
def tutorial_detail(
    tutorial_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    found = tutorial_store.get_published(conn, tutorial_id)
    if found is None:
        raise HTTPException(status_code=404, detail="tutorial_not_found")
    content, meta = found
    token = user["opaque_token"]
    summary = progress.tutorial_summary(conn, token, tutorial_id, content)
    runtime_ids = set(tutorial_store.runtime_step_ids(content))

    faq_counts = {
        r["step_id"]: r["n"]
        for r in conn.execute(
            """SELECT step_id, COUNT(*) AS n FROM faqs
               WHERE tutorial_id = ? AND is_published = 1 GROUP BY step_id""",
            (tutorial_id,),
        ).fetchall()
    }

    sections = []
    for sec in content.get("sections", []):
        steps = []
        for st in sec.get("steps", []):
            sid = st.get("step_id")
            if sid not in runtime_ids:
                continue  # authored but not in the live run
            state = summary["step_statuses"].get(sid, {"status": "not_started", "fail_count": 0})
            steps.append(
                {
                    "step_id": sid,
                    "title": st.get("title"),
                    "app": st.get("app"),
                    "status": state["status"],
                    "fail_count": state["fail_count"],
                    "faq_count": faq_counts.get(sid, 0),
                }
            )
        if steps:
            sections.append({"section": sec.get("section"), "app": sec.get("app"), "steps": steps})

    submissions = [
        {
            "submission_id": r["id"],
            "filename": r["filename"],
            "ok": bool(r["ok"]),
            "score": r["score"],
            "total": r["total"],
            "submitted_at": r["submitted_at"],
        }
        for r in conn.execute(
            """SELECT * FROM report_submissions
               WHERE session_token = ? AND tutorial_id = ?
               ORDER BY submitted_at DESC LIMIT 10""",
            (token, tutorial_id),
        ).fetchall()
    ]

    return {
        "tutorial_id": tutorial_id,
        "title": meta["title"],
        "version": meta["latest_published_version"],
        "product": meta["product"],
        "is_mandatory": bool(meta["is_mandatory"]),
        "problem": content.get("problem"),
        "expected_result": (content.get("report_checks") or {}).get("expected_result"),
        "status": summary["status"],
        "percent": summary["percent"],
        "steps_total": summary["steps_total"],
        "steps_completed": summary["steps_completed"],
        "sections": sections,
        "needs_report": summary["needs_report"],
        "report": summary["report"],
        "report_guidelines": meta["report_guidelines"],
        "report_submissions": submissions,
        "quiz": summary["quiz"],
    }

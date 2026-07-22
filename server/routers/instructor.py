"""Instructor endpoints: sections + class codes, cohort progress matrix,
activity feed, quiz score distributions, and the tutorial library
(upload -> validate -> immutable version -> publish).

FERPA note: this is the ONE place the username <-> opaque-token join is
performed — instructor-facing dashboards need names to be useful. Analytics
tables themselves never store usernames, and exports stay token-only.
"""

import json
import sqlite3
import time

import csv
import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from ..deps import csrf_check, get_db, get_settings, require_instructor
from ..models import SectionCreate, SectionResponse
from ..security import new_class_code
from ..services import faq_service, progress, quiz_store, tutorial_store
from ..services.tutorial_store import TutorialValidationError

router = APIRouter(
    prefix="/api/instructor",
    tags=["instructor"],
    dependencies=[Depends(require_instructor)],
)


def _section_response(conn: sqlite3.Connection, row: sqlite3.Row) -> SectionResponse:
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE section_id = ? AND role = 'student'",
        (row["id"],),
    ).fetchone()["n"]
    return SectionResponse(
        id=row["id"], name=row["name"], class_code=row["class_code"],
        is_active=bool(row["is_active"]), student_count=count,
    )


@router.get("/sections")
def list_sections(conn: sqlite3.Connection = Depends(get_db)) -> list[SectionResponse]:
    rows = conn.execute("SELECT * FROM sections ORDER BY created_at").fetchall()
    return [_section_response(conn, r) for r in rows]


@router.post("/sections", status_code=201, dependencies=[Depends(csrf_check)])
def create_section(
    body: SectionCreate, conn: sqlite3.Connection = Depends(get_db)
) -> SectionResponse:
    cur = conn.execute(
        "INSERT INTO sections (name, class_code, created_at) VALUES (?,?,?)",
        (body.name.strip(), new_class_code(), time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sections WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _section_response(conn, row)


@router.post("/sections/{section_id}/regenerate-code", dependencies=[Depends(csrf_check)])
def regenerate_code(
    section_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> SectionResponse:
    row = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="section_not_found")
    conn.execute(
        "UPDATE sections SET class_code = ? WHERE id = ?", (new_class_code(), section_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
    return _section_response(conn, row)


# ── cohort progress ──────────────────────────────────────────────────────


@router.get("/progress")
def progress_matrix(conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Students x published-tutorials completion matrix + headline tiles.
    Computed on read — cohort <= 30, a handful of tutorials."""
    published = []
    for entry in tutorial_store.list_published(conn):
        found = tutorial_store.get_published(conn, entry["tutorial_id"])
        if found:
            published.append((entry, found[0]))

    students = conn.execute(
        """SELECT u.username, u.opaque_token, s.name AS section
           FROM users u LEFT JOIN sections s ON s.id = u.section_id
           WHERE u.role = 'student' AND u.is_active = 1
           ORDER BY s.name, u.username COLLATE NOCASE""",
    ).fetchall()

    rows = []
    percent_sum = 0
    percent_n = 0
    completed_cells = 0
    for stu in students:
        cells = {}
        for entry, content in published:
            summary = progress.tutorial_summary(
                conn, stu["opaque_token"], entry["tutorial_id"], content
            )
            cells[entry["tutorial_id"]] = {
                "status": summary["status"],
                "percent": summary["percent"],
                "steps_completed": summary["steps_completed"],
                "steps_total": summary["steps_total"],
                "report_ok": bool(summary["report"] and summary["report"]["ok"]),
                "quiz_attempts": summary["quiz"]["attempts"] if summary["quiz"] else None,
                "quiz_best": summary["quiz"]["best_score"] if summary["quiz"] else None,
            }
            percent_sum += summary["percent"]
            percent_n += 1
            completed_cells += summary["status"] == "completed"
        rows.append(
            {
                "username": stu["username"],
                "opaque_token": stu["opaque_token"],
                "section": stu["section"],
                "cells": cells,
            }
        )

    reports_passed = conn.execute(
        """SELECT COUNT(*) AS n FROM
           (SELECT DISTINCT session_token, tutorial_id FROM report_submissions WHERE ok = 1)"""
    ).fetchone()["n"]
    quiz_avg = conn.execute(
        """SELECT AVG(best) AS avg FROM
           (SELECT MAX(score) AS best FROM quiz_submissions GROUP BY session_token, quiz_id)"""
    ).fetchone()["avg"]

    return {
        "tutorials": [
            {
                "tutorial_id": e["tutorial_id"],
                "title": e["title"],
                "is_mandatory": e["is_mandatory"],
            }
            for e, _ in published
        ],
        "students": rows,
        "tiles": {
            "students": len(students),
            "avg_completion": round(percent_sum / percent_n) if percent_n else 0,
            "tutorials_completed": completed_cells,
            "reports_passed": reports_passed,
            "quiz_avg": round(quiz_avg * 100) if quiz_avg is not None else None,
        },
    }


@router.get("/activity")
def activity_feed(limit: int = 50, conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """Most recent student activity, merged across events, reports, and
    quizzes. Usernames resolved here (see module docstring)."""
    limit = max(1, min(limit, 200))
    rows = conn.execute(
        """
        SELECT * FROM (
          SELECT 'event' AS kind, e.action_type AS detail, e.step_id AS step_id,
                 e.tutorial_id, e.session_token, e.timestamp AS ts, NULL AS score, NULL AS total
          FROM action_events e
          UNION ALL
          SELECT 'report', CASE WHEN r.ok = 1 THEN 'passed' ELSE 'failed' END, NULL,
                 r.tutorial_id, r.session_token, r.submitted_at, r.score, r.total
          FROM report_submissions r
          UNION ALL
          SELECT 'quiz', 'submitted', NULL,
                 q.tutorial_id, q.session_token, q.submitted_at,
                 q.score, NULL
          FROM quiz_submissions q
        )
        ORDER BY ts DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    usernames = {
        r["opaque_token"]: r["username"]
        for r in conn.execute(
            "SELECT opaque_token, username FROM users WHERE opaque_token IS NOT NULL"
        ).fetchall()
    }
    titles = {
        r["tutorial_id"]: r["title"]
        for r in conn.execute("SELECT tutorial_id, title FROM tutorials").fetchall()
    }
    return [
        {
            "kind": r["kind"],
            "detail": r["detail"],
            "step_id": r["step_id"],
            "tutorial_id": r["tutorial_id"],
            "tutorial_title": titles.get(r["tutorial_id"], r["tutorial_id"]),
            "username": usernames.get(r["session_token"], r["session_token"]),
            "score": r["score"],
            "total": r["total"],
            "timestamp": r["ts"],
        }
        for r in rows
    ]


@router.get("/quiz-stats")
def quiz_stats(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """Per quiz: participation + a discrete histogram of each student's BEST
    correct-count (scores on an N-question quiz are k/N — buckets would lie)."""
    out = []
    for quiz in conn.execute(
        "SELECT * FROM quizzes WHERE is_published = 1 ORDER BY updated_at"
    ).fetchall():
        total_q = conn.execute(
            "SELECT COUNT(*) AS n FROM quiz_questions WHERE quiz_id = ?", (quiz["quiz_id"],)
        ).fetchone()["n"]
        bests = [
            r["best"]
            for r in conn.execute(
                """SELECT MAX(score) AS best FROM quiz_submissions
                   WHERE quiz_id = ? GROUP BY session_token""",
                (quiz["quiz_id"],),
            ).fetchall()
        ]
        histogram = [0] * (total_q + 1)
        for b in bests:
            histogram[round(b * total_q)] += 1
        attempts = conn.execute(
            "SELECT COUNT(*) AS n FROM quiz_submissions WHERE quiz_id = ?", (quiz["quiz_id"],)
        ).fetchone()["n"]
        out.append(
            {
                "quiz_id": quiz["quiz_id"],
                "title": quiz["title"],
                "tutorial_id": quiz["tutorial_id"],
                "total_questions": total_q,
                "students": len(bests),
                "attempts": attempts,
                "avg_pct": round(100 * sum(bests) / len(bests)) if bests else None,
                "histogram": [
                    {"correct": i, "count": c} for i, c in enumerate(histogram)
                ],
            }
        )
    return out


# ── tutorial library ─────────────────────────────────────────────────────


def _library_entry(conn: sqlite3.Connection, meta: sqlite3.Row) -> dict:
    versions = [
        {
            "version": v["version"],
            "uploaded_at": v["uploaded_at"],
            "warnings": json.loads(v["validation_findings"]),
        }
        for v in conn.execute(
            """SELECT version, uploaded_at, validation_findings FROM tutorial_versions
               WHERE tutorial_id = ? ORDER BY version DESC""",
            (meta["tutorial_id"],),
        ).fetchall()
    ]
    return {
        "tutorial_id": meta["tutorial_id"],
        "title": meta["title"],
        "product": meta["product"],
        "is_mandatory": bool(meta["is_mandatory"]),
        "quiz_id": meta["quiz_id"],
        "published_version": meta["latest_published_version"],
        "is_archived": bool(meta["is_archived"]),
        "report_guidelines": meta["report_guidelines"],
        "versions": versions,
    }


@router.get("/tutorials")
def library(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """Every tutorial including drafts (unpublished) — unlike the student
    catalog, which only lists published ones."""
    return [
        _library_entry(conn, meta)
        for meta in conn.execute("SELECT * FROM tutorials ORDER BY created_at").fetchall()
    ]


@router.post("/tutorials", status_code=201, dependencies=[Depends(csrf_check)])
def upload_tutorial(
    request: Request,
    file: UploadFile,
    product: str = Form("mechanical"),
    is_mandatory: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_instructor),
) -> dict:
    """Validate + store a new immutable version. NOT auto-published — review
    the warnings, then hit /publish. Validator errors reject with 422."""
    raw = file.file.read()
    settings = get_settings(request)
    try:
        result = tutorial_store.import_tutorial(
            conn, settings, raw,
            product=product, is_mandatory=is_mandatory,
            uploaded_by=user["id"], publish=False,
        )
    except TutorialValidationError as exc:
        raise HTTPException(status_code=422, detail={"findings": exc.findings})
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"findings": [{"severity": "error", "where": "file", "message": str(exc)}]},
        )
    return result


@router.post("/tutorials/{tutorial_id}/publish", dependencies=[Depends(csrf_check)])
def publish_tutorial(
    tutorial_id: str, body: dict, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    version = body.get("version")
    row = conn.execute(
        "SELECT 1 FROM tutorial_versions WHERE tutorial_id = ? AND version = ?",
        (tutorial_id, version),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="version_not_found")
    conn.execute(
        "UPDATE tutorials SET latest_published_version = ? WHERE tutorial_id = ?",
        (version, tutorial_id),
    )
    conn.commit()
    return {"tutorial_id": tutorial_id, "published_version": version}


@router.post("/tutorials/{tutorial_id}/settings", dependencies=[Depends(csrf_check)])
def tutorial_settings(
    tutorial_id: str, body: dict, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    meta = conn.execute(
        "SELECT * FROM tutorials WHERE tutorial_id = ?", (tutorial_id,)
    ).fetchone()
    if meta is None:
        raise HTTPException(status_code=404, detail="tutorial_not_found")
    if "is_mandatory" in body:
        conn.execute(
            "UPDATE tutorials SET is_mandatory = ? WHERE tutorial_id = ?",
            (int(bool(body["is_mandatory"])), tutorial_id),
        )
    if "report_guidelines" in body:
        raw = body["report_guidelines"]
        if raw is not None and not isinstance(raw, str):
            raise HTTPException(status_code=422, detail="report_guidelines_must_be_string")
        text = (raw or "").strip()
        if len(text) > 4000:
            raise HTTPException(status_code=422, detail="report_guidelines_too_long")
        conn.execute(
            "UPDATE tutorials SET report_guidelines = ? WHERE tutorial_id = ?",
            (text or None, tutorial_id),
        )
    conn.commit()
    meta = conn.execute(
        "SELECT * FROM tutorials WHERE tutorial_id = ?", (tutorial_id,)
    ).fetchone()
    return _library_entry(conn, meta)


# ── quiz upload ──────────────────────────────────────────────────────────


@router.post("/quizzes", status_code=201, dependencies=[Depends(csrf_check)])
def upload_quiz(
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Upload an authored quiz JSON (see mock_server/data/quizzes/_template.json).
    Validator errors reject with 422 + findings; a valid quiz publishes
    immediately (re-uploading the same quiz_id replaces its questions)."""
    try:
        data = json.loads(file.file.read().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"findings": [{"severity": "error", "where": "file", "message": f"not valid JSON: {exc}"}]},
        )
    findings = quiz_store.validate_quiz(conn, data)
    if any(f["severity"] == "error" for f in findings):
        raise HTTPException(status_code=422, detail={"findings": findings})
    replaced = conn.execute(
        "SELECT 1 FROM quizzes WHERE quiz_id = ?", (data["quiz_id"],)
    ).fetchone() is not None
    quiz_id = quiz_store.import_quiz(conn, data)
    return {
        "quiz_id": quiz_id,
        "tutorial_id": data["tutorial_id"],
        "questions": len(data["questions"]),
        "replaced": replaced,
        "warnings": [f for f in findings if f["severity"] == "warning"],
    }


# ── quiz analytics ───────────────────────────────────────────────────────


@router.get("/quizzes/{quiz_id}/analytics")
def quiz_analytics(quiz_id: str, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Per-question difficulty and per-concept mastery, computed over each
    student's FIRST attempt — retakes happen after seeing the explanations,
    so later attempts measure memory of the answer, not difficulty."""
    meta = conn.execute(
        "SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,)
    ).fetchone()
    if meta is None:
        raise HTTPException(status_code=404, detail="quiz_not_found")
    questions = conn.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY position", (quiz_id,)
    ).fetchall()
    firsts = conn.execute(
        """SELECT answers FROM quiz_submissions
           WHERE quiz_id = ? AND attempt = 1""",
        (quiz_id,),
    ).fetchall()
    sheets = [json.loads(r["answers"]) for r in firsts]

    q_out = []
    concepts: dict[str, dict] = {}
    for i, q in enumerate(questions):
        correct = sum(
            1 for sheet in sheets if i < len(sheet) and sheet[i] == q["correct_index"]
        )
        attempts = len(sheets)
        q_out.append(
            {
                "question_id": q["id"],
                "position": q["position"],
                "text": q["text"],
                "concept_tag": q["concept_tag"],
                "correct_index": q["correct_index"],
                "options": json.loads(q["options"]),
                "attempts": attempts,
                "correct_pct": round(100 * correct / attempts) if attempts else None,
            }
        )
        tag = q["concept_tag"] or "general"
        agg = concepts.setdefault(tag, {"correct": 0, "total": 0})
        agg["total"] += attempts
        agg["correct"] += correct

    return {
        "quiz_id": quiz_id,
        "title": meta["title"],
        "tutorial_id": meta["tutorial_id"],
        "first_attempt_students": len(sheets),
        "questions": q_out,
        "concepts": [
            {
                "tag": tag,
                "correct": c["correct"],
                "total": c["total"],
                "pct": round(100 * c["correct"] / c["total"]) if c["total"] else None,
            }
            for tag, c in concepts.items()
        ],
    }


# ── FAQ pipeline ─────────────────────────────────────────────────────────


@router.post("/faqs/refresh", dependencies=[Depends(csrf_check)])
def refresh_faq_candidates(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    return faq_service.mine_candidates(conn, get_settings(request))


@router.get("/faqs/candidates")
def faq_candidates(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM faq_candidates
           ORDER BY CASE status WHEN 'candidate' THEN 0 WHEN 'drafted' THEN 1
                    WHEN 'approved' THEN 2 ELSE 3 END,
                    failure_rate DESC"""
    ).fetchall()
    return [faq_service.candidate_context(conn, r) for r in rows]


@router.post("/faqs/candidates/{candidate_id}/draft", dependencies=[Depends(csrf_check)])
def draft_faq(
    candidate_id: int, request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    try:
        return faq_service.draft_candidate(conn, get_settings(request), candidate_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"draft_failed: {exc}")


@router.post("/faqs/candidates/{candidate_id}/approve", dependencies=[Depends(csrf_check)])
def approve_faq(
    candidate_id: int,
    body: dict,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_instructor),
) -> dict:
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not question or not answer:
        raise HTTPException(status_code=422, detail="question_and_answer_required")
    try:
        return faq_service.approve_candidate(conn, candidate_id, question, answer, user["id"])
    except KeyError:
        raise HTTPException(status_code=404, detail="candidate_not_found")


@router.post("/faqs/candidates/{candidate_id}/reject", dependencies=[Depends(csrf_check)])
def reject_faq(
    candidate_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_instructor),
) -> dict:
    faq_service.reject_candidate(conn, candidate_id, user["id"])
    return {"ok": True}


@router.get("/faqs")
def published_faqs(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    return [
        {
            "faq_id": r["id"],
            "tutorial_id": r["tutorial_id"],
            "step_id": r["step_id"],
            "question": r["question"],
            "answer": r["answer"],
            "created_at": r["created_at"],
        }
        for r in conn.execute(
            "SELECT * FROM faqs WHERE is_published = 1 ORDER BY created_at DESC"
        ).fetchall()
    ]


@router.delete("/faqs/{faq_id}")
def unpublish_faq(faq_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    conn.execute("UPDATE faqs SET is_published = 0 WHERE id = ?", (faq_id,))
    conn.commit()
    return {"ok": True}


# ── CSV exports (FERPA: token-only, verbatim from the event tables) ──────

_EXPORTS = {
    "action_events": (
        "SELECT session_token, tutorial_id, step_id, action_type,"
        " uia_automation_id, timestamp, extra FROM action_events ORDER BY timestamp"
    ),
    "quiz_submissions": (
        "SELECT session_token, quiz_id, tutorial_id, answers, score, attempt,"
        " submitted_at FROM quiz_submissions ORDER BY submitted_at"
    ),
    "report_submissions": (
        "SELECT session_token, tutorial_id, filename, ok, score, total,"
        " submitted_at FROM report_submissions ORDER BY submitted_at"
    ),
    "chatbot_queries": (
        "SELECT session_token, tutorial_id, step_id, question, model,"
        " duration_ms, created_at FROM chatbot_queries ORDER BY created_at"
    ),
}


@router.get("/export/{table}.csv")
def export_csv(table: str, conn: sqlite3.Connection = Depends(get_db)) -> PlainTextResponse:
    """Research exports. Deliberately selects from the analytics tables
    verbatim — they only ever contain opaque tokens, so the export cannot
    leak identity even by accident."""
    sql = _EXPORTS.get(table)
    if sql is None:
        raise HTTPException(status_code=404, detail="unknown_export")
    cur = conn.execute(sql)
    rows = cur.fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([d[0] for d in cur.description])
    writer.writerows([tuple(r) for r in rows])
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
    )

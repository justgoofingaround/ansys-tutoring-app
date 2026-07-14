"""Report upload + rubric validation (synchronous — the SPA shows an
'Analyzing…' state; validation runs in FastAPI's threadpool because this is
a sync `def` route, so the event loop never blocks)."""

import json
import re
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..config import Settings
from ..deps import csrf_check, get_db, get_settings, require_student
from ..services import report_verify, tutorial_store

router = APIRouter(prefix="/api", tags=["reports"])

ALLOWED_SUFFIXES = {".docx", ".pdf", ".html", ".htm", ".txt", ".md", ".markdown", ".json"}


@router.post("/tutorials/{tutorial_id}/report", dependencies=[Depends(csrf_check)])
def upload_report(
    tutorial_id: str,
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
    settings: Settings = Depends(get_settings),
) -> dict:
    found = tutorial_store.get_published(conn, tutorial_id)
    if found is None:
        raise HTTPException(status_code=404, detail="tutorial_not_found")
    content, meta = found
    if not content.get("report_checks"):
        raise HTTPException(status_code=400, detail="tutorial_has_no_report_checks")

    filename = Path(file.filename or "report").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported_report_format")

    token = user["opaque_token"]
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    dest_dir = settings.reports_dir / token
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{int(time.time())}_{safe_name}"

    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_report_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="report_too_large")
            out.write(chunk)

    try:
        result = report_verify.validate_report(dest, content, use_llm=settings.enable_llm)
    except (ValueError, RuntimeError) as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))

    cur = conn.execute(
        """INSERT INTO report_submissions
           (session_token, tutorial_id, tutorial_version, filename, stored_path,
            ok, score, total, checks, feedback, llm_review, submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            token, tutorial_id, meta["latest_published_version"], filename, str(dest),
            int(result["ok"]), result["score"], result["total"],
            json.dumps(result["checks"]), result["feedback"],
            json.dumps(result.get("llm_review")), time.time(),
        ),
    )
    conn.commit()
    return {
        "submission_id": cur.lastrowid,
        "ok": result["ok"],
        "score": result["score"],
        "total": result["total"],
        "checks": result["checks"],
        "feedback": result["feedback"],
        "llm_review": result.get("llm_review"),
        # extracted report text is deliberately NOT returned
    }


@router.get("/tutorials/{tutorial_id}/reports/mine")
def my_reports(
    tutorial_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM report_submissions
           WHERE session_token = ? AND tutorial_id = ?
           ORDER BY submitted_at DESC LIMIT 20""",
        (user["opaque_token"], tutorial_id),
    ).fetchall()
    return [
        {
            "submission_id": r["id"],
            "filename": r["filename"],
            "ok": bool(r["ok"]),
            "score": r["score"],
            "total": r["total"],
            "checks": json.loads(r["checks"]),
            "feedback": r["feedback"],
            "llm_review": json.loads(r["llm_review"]) if r["llm_review"] else None,
            "submitted_at": r["submitted_at"],
        }
        for r in rows
    ]

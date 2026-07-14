"""Instructor endpoints. M1: sections + class codes. Later milestones add
progress matrix, tutorial library, quiz management, analytics, FAQ queue."""

import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import csrf_check, get_db, require_instructor
from ..models import SectionCreate, SectionResponse
from ..security import new_class_code

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

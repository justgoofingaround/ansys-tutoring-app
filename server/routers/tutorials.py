"""Content serving — used by the web SPA and (later) the desktop overlay.
Paths after /api match the sibling repo's api_client.py contract."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..deps import current_user, get_db
from ..services import guide_bundle, tutorial_store

router = APIRouter(prefix="/api", tags=["tutorials"], dependencies=[Depends(current_user)])


@router.get("/tutorials")
def list_tutorials(
    product: str | None = None,
    is_mandatory: bool | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    return tutorial_store.list_published(conn, product, is_mandatory)


@router.get("/tutorials/{tutorial_id}")
def get_tutorial(
    tutorial_id: str,
    version: int | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    found = tutorial_store.get_published(conn, tutorial_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail="tutorial_not_found")
    content, meta = found
    content["_meta"] = {
        "version": version or meta["latest_published_version"],
        "product": meta["product"],
        "is_mandatory": bool(meta["is_mandatory"]),
        "quiz_id": meta["quiz_id"],
    }
    return content


def _faq_rows(rows) -> list[dict]:
    return [
        {
            "faq_id": r["id"],
            "step_id": r["step_id"],
            "question": r["question"],
            "answer": r["answer"],
        }
        for r in rows
    ]


@router.get("/tutorials/{tutorial_id}/faqs")
def tutorial_faqs(tutorial_id: str, conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM faqs WHERE tutorial_id = ? AND is_published = 1 ORDER BY created_at",
        (tutorial_id,),
    ).fetchall()
    return _faq_rows(rows)


@router.get("/tutorials/{tutorial_id}/steps/{step_id}/faqs")
def step_faqs(
    tutorial_id: str, step_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM faqs WHERE tutorial_id = ? AND step_id = ? AND is_published = 1
           ORDER BY created_at""",
        (tutorial_id, step_id),
    ).fetchall()
    return _faq_rows(rows)

@router.get("/tutorials/{tutorial_id}/desktop-guide-bundle")
def desktop_guide_bundle(tutorial_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    try:
        payload, filename, missing = guide_bundle.build_desktop_guide_bundle(conn, tutorial_id)
    except ValueError as exc:
        if str(exc) == "tutorial_not_found":
            raise HTTPException(status_code=404, detail="tutorial_not_found") from exc
        raise

    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Guide-Missing-Assets": ",".join(missing),
        },
    )

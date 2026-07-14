"""Compass chatbot: consent gate + streaming query endpoint.

Streaming protocol (SSE over a POST body, parsed client-side from the
response stream):

    event: meta     data: {"model": "..."}
    event: token    data: {"t": "piece of the answer"}   (repeated)
    event: sources  data: {"sources": ["citation", ...]}
    event: done     data: {"duration_ms": 1234}
    event: error    data: {"detail": "..."}              (terminal, instead of done)

stream=false returns one JSON body instead — the overlay contract's shape.

FERPA: chatbot_queries logs carry the opaque token only, and logging is
gated on explicit consent (403 consent_required until granted).
"""

import json
import queue
import sqlite3
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import db as dbmod
from ..deps import get_db, get_settings, require_student
from ..models import ChatConsentIn, ChatQueryIn
from ..services import chatbot_service, tutorial_store

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


@router.get("/consent")
def get_consent(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    row = conn.execute(
        "SELECT 1 FROM consents WHERE user_id = ? AND kind = 'chatbot'", (user["id"],)
    ).fetchone()
    return {"granted": row is not None}


@router.post("/consent")
def set_consent(
    body: ChatConsentIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    if body.granted:
        conn.execute(
            "INSERT OR IGNORE INTO consents (user_id, kind, granted_at) VALUES (?, 'chatbot', ?)",
            (user["id"], time.time()),
        )
    else:
        conn.execute(
            "DELETE FROM consents WHERE user_id = ? AND kind = 'chatbot'", (user["id"],)
        )
    conn.commit()
    return {"granted": body.granted}


def _tutorial_context(conn: sqlite3.Connection, body: ChatQueryIn) -> str | None:
    """Human-readable context string for the prompt (the architecture doc's
    'Context fetcher'): tutorial title, plus the step title if given."""
    if not body.tutorial_id:
        return None
    found = tutorial_store.get_published(conn, body.tutorial_id)
    if not found:
        return None
    content, meta = found
    ctx = meta["title"]
    if body.step_id:
        for sec in content.get("sections", []):
            for st in sec.get("steps", []):
                if st.get("step_id") == body.step_id:
                    ctx += f" — step: {st.get('title')}"
    return ctx


def _log_query(settings, token, body: ChatQueryIn, answer, sources, model, duration_ms):
    """Own connection: the request-scoped one may already be torn down by
    the time a streamed response finishes."""
    conn = dbmod.connect(settings.db_path)
    try:
        conn.execute(
            """INSERT INTO chatbot_queries
               (session_token, tutorial_id, step_id, question, answer, sources,
                model, duration_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                token, body.tutorial_id, body.step_id, body.question, answer,
                json.dumps(sources), model, duration_ms, time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/query")
def chat_query(
    body: ChatQueryIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
):
    if not conn.execute(
        "SELECT 1 FROM consents WHERE user_id = ? AND kind = 'chatbot'", (user["id"],)
    ).fetchone():
        raise HTTPException(status_code=403, detail="consent_required")

    settings = get_settings(request)
    engine = chatbot_service.get_engine(settings)
    context = _tutorial_context(conn, body)
    token = user["opaque_token"]
    started = time.time()

    if not body.stream:
        try:
            answer, sources = engine.generate(body.question, context, lambda _t: None)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"chatbot_unavailable: {exc}")
        duration_ms = int((time.time() - started) * 1000)
        _log_query(settings, token, body, answer, sources, engine.model, duration_ms)
        return {
            "answer": answer,
            "sources": sources,
            "model": engine.model,
            "duration_ms": duration_ms,
        }

    # Streaming: generation runs on a worker thread feeding a queue; the
    # response generator drains it. The worker owns logging so a completed
    # generation is recorded even if the client disconnects mid-stream.
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            answer, sources = engine.generate(
                body.question, context, lambda t: q.put(("token", t))
            )
            duration_ms = int((time.time() - started) * 1000)
            _log_query(settings, token, body, answer, sources, engine.model, duration_ms)
            q.put(("sources", sources))
            q.put(("done", duration_ms))
        except Exception as exc:
            q.put(("error", str(exc)))

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        yield _sse("meta", {"model": engine.model})
        while True:
            kind, payload = q.get()
            if kind == "token":
                yield _sse("token", {"t": payload})
            elif kind == "sources":
                yield _sse("sources", {"sources": payload})
            elif kind == "done":
                yield _sse("done", {"duration_ms": payload})
                return
            elif kind == "error":
                yield _sse("error", {"detail": payload})
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

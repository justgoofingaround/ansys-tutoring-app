"""FastAPI dependencies: DB connection, auth (cookie OR X-Session-Token), roles, CSRF."""

import sqlite3
import time
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from . import db as dbmod
from .config import SESSION_COOKIE, Settings
from .security import hash_session_token


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = dbmod.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _user_from_cookie(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    now = time.time()
    row = conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.revoked = 0 AND s.expires_at > ? AND u.is_active = 1""",
        (hash_session_token(token), now),
    ).fetchone()
    if row is not None:
        # Sliding expiry: refresh on use.
        ttl_days = request.app.state.settings.session_ttl_days
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
            (now + ttl_days * 86400, hash_session_token(token)),
        )
        conn.commit()
    return row


def _user_from_header(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Overlay auth path: the opaque student token as X-Session-Token."""
    token = request.headers.get("X-Session-Token")
    if not token:
        return None
    return conn.execute(
        "SELECT * FROM users WHERE opaque_token = ? AND is_active = 1", (token,)
    ).fetchone()


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    user = _user_from_cookie(request, conn) or _user_from_header(request, conn)
    if user is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user


def require_instructor(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if user["role"] != "instructor":
        raise HTTPException(status_code=403, detail="instructor_only")
    return user


def require_student(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="student_only")
    return user


def csrf_check(request: Request) -> None:
    """State-changing cookie-authed routes: SameSite=Lax blocks cross-site POSTs
    in modern browsers; belt-and-braces we additionally require a header shape
    that cross-origin HTML forms cannot produce without a CORS preflight."""
    if request.headers.get("X-Session-Token"):
        return  # header-authed (overlay) requests are not CSRF-able
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return
    if request.headers.get("X-Requested-With") == "fetch":
        return  # multipart uploads from the SPA set this
    raise HTTPException(status_code=403, detail="csrf_rejected")

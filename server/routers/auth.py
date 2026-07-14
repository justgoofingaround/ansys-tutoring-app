"""Auth: student self-registration (class code), login, logout, me."""

import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import SESSION_COOKIE, Settings
from ..deps import csrf_check, current_user, get_db, get_settings
from ..models import LoginRequest, MeResponse, RegisterRequest
from ..security import (
    hash_password,
    hash_session_token,
    new_opaque_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _start_session(
    response: Response, conn: sqlite3.Connection, user_id: int, settings: Settings
) -> None:
    token = new_session_token()
    now = time.time()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (hash_session_token(token), user_id, now, now + settings.session_ttl_days * 86400),
    )
    conn.commit()
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=int(settings.session_ttl_days * 86400),
        httponly=True, samesite="lax",
        # Secure flag off: plain-HTTP NYU LAN pilot (documented limitation).
    )


def _me(conn: sqlite3.Connection, user: sqlite3.Row) -> MeResponse:
    section = None
    if user["section_id"] is not None:
        row = conn.execute("SELECT name FROM sections WHERE id = ?", (user["section_id"],)).fetchone()
        section = row["name"] if row else None
    consent = conn.execute(
        "SELECT 1 FROM consents WHERE user_id = ? AND kind = 'chatbot'", (user["id"],)
    ).fetchone()
    return MeResponse(
        username=user["username"],
        role=user["role"],
        section=section,
        opaque_token=user["opaque_token"],
        chatbot_consent=consent is not None,
    )


@router.post("/register", status_code=201, dependencies=[Depends(csrf_check)])
def register(
    body: RegisterRequest,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    section = conn.execute(
        "SELECT * FROM sections WHERE class_code = ? AND is_active = 1",
        (body.class_code.strip().upper(),),
    ).fetchone()
    if section is None:
        raise HTTPException(status_code=400, detail="invalid_class_code")
    if conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (body.username.strip(),)
    ).fetchone():
        raise HTTPException(status_code=409, detail="username_taken")
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, section_id, opaque_token, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (
            body.username.strip(),
            hash_password(body.password),
            "student",
            section["id"],
            new_opaque_token(conn),
            time.time(),
        ),
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    _start_session(response, conn, user["id"], settings)
    return _me(conn, user)


@router.post("/login", dependencies=[Depends(csrf_check)])
def login(
    body: LoginRequest,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (body.username.strip(),)
    ).fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="bad_credentials")
    _start_session(response, conn, user["id"], settings)
    return _me(conn, user)


@router.post("/logout", dependencies=[Depends(csrf_check)])
def logout(
    request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE token_hash = ?",
            (hash_session_token(token),),
        )
        conn.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(
    conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)
) -> MeResponse:
    return _me(conn, user)

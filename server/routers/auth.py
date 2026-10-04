"""Auth: roster-based student registration with emailed confirmation, login,
logout, me.

Registration no longer uses a shared class code - a student can only register
if their address is on a section's roster (services/roster.py), which is also
what assigns them to that section. Registering does NOT sign them in: the
account stays unverified until the one-time link mailed to that address is
opened, so knowing a classmate's address is not enough to claim their place.
"""

import logging
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import SESSION_COOKIE, Settings
from ..deps import csrf_check, current_user, get_db, get_settings
from ..models import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResendRequest,
    ResetPasswordRequest,
)
from ..security import (
    hash_password,
    hash_session_token,
    new_opaque_token,
    new_session_token,
    verify_password,
)
from ..services import mailer as mailer_mod
from ..services import roster

router = APIRouter(prefix="/api/auth", tags=["auth"])

log = logging.getLogger("tutoring_hub.auth")


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
        # Secure only when the deployment terminates TLS (COOKIE_SECURE=1);
        # plain-HTTP LAN/dev runs keep it off so the cookie still sticks.
        secure=settings.cookie_secure,
    )


def _me(conn: sqlite3.Connection, user: sqlite3.Row, settings: Settings) -> MeResponse:
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
        ai_enabled=settings.enable_ai,
    )


def _issue_verification(
    conn: sqlite3.Connection, settings: Settings, user: sqlite3.Row, name: str
) -> bool:
    """Mint a single-use link, store only its hash (same discipline as
    sessions), and hand it to the mailer. Returns whether the mail went out.

    A send failure is NOT fatal: the account and its link already exist, so the
    instructor can confirm the student from the class list. Failing the whole
    request instead would leave a claimed roster row that nobody can use, and
    would take registration down with the mail server — the opposite of the
    intended degradation.
    """
    token = new_session_token()
    now = time.time()
    conn.execute(
        """INSERT INTO email_verifications (token_hash, user_id, created_at, expires_at)
           VALUES (?,?,?,?)""",
        (
            hash_session_token(token), user["id"], now,
            now + settings.verification_ttl_hours * 3600,
        ),
    )
    conn.commit()
    url = f"{settings.app_base_url.rstrip('/')}/verify?token={token}"
    mailer = mailer_mod.get_mailer(settings)
    try:
        mailer.send_verification(
            user["email"], name, url, int(settings.verification_ttl_hours)
        )
        # A mailer that only logs the link has not actually sent anything, so
        # do not let the UI claim it did.
        return getattr(mailer, "delivers", True)
    except Exception:
        log.exception(
            "Could not send the confirmation email to %s. The account exists and "
            "the instructor can confirm it from the class list. Link: %s",
            user["email"], url,
        )
        return False


@router.post("/register", status_code=202, dependencies=[Depends(csrf_check)])
def register(
    body: RegisterRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """202, not 201 + session: the account exists but cannot be used until the
    emailed confirmation link is opened."""
    email = body.email.strip()
    entry = roster.entry_for_email(conn, email)
    if entry is None:
        raise HTTPException(status_code=400, detail="not_on_roster")

    if entry["claimed_by_user_id"] is not None:
        holder = conn.execute(
            "SELECT * FROM users WHERE id = ?", (entry["claimed_by_user_id"],)
        ).fetchone()
        if holder is not None and holder["email_verified_at"] is not None:
            raise HTTPException(status_code=409, detail="already_claimed")
        # The row is held by an account that never confirmed the address, so
        # whoever registered it has not proved they can read that mailbox.
        # The real owner can take it back simply by registering: they receive
        # the new link, the impostor's pending account is discarded. Without
        # this, claiming someone else's address would lock them out for good.
        # Release the claim before deleting the account it points at, or the
        # foreign key from roster_entries blocks the delete.
        conn.execute(
            "UPDATE roster_entries SET claimed_by_user_id = NULL WHERE id = ?", (entry["id"],)
        )
        if holder is not None:
            log.warning(
                "Re-registration for %s discards an unconfirmed account (user %s).",
                email, holder["id"],
            )
            for table in ("sessions", "email_verifications", "password_resets", "consents"):
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (holder["id"],))
            conn.execute("DELETE FROM users WHERE id = ?", (holder["id"],))
        conn.commit()

    display_name = (entry["full_name"] or "").strip() or email
    # username doubles as the display name and must stay unique; disambiguate
    # rather than turning a student away because a namesake registered first.
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (display_name,)).fetchone():
        display_name = f"{display_name} ({entry['netid'] or email.split('@')[0]})"

    cur = conn.execute(
        """INSERT INTO users
           (username, password_hash, role, section_id, opaque_token, created_at, email)
           VALUES (?,?,?,?,?,?,?)""",
        (
            display_name,
            hash_password(body.password),
            "student",
            entry["section_id"],
            new_opaque_token(conn),
            time.time(),
            email,
        ),
    )
    user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.execute(
        "UPDATE roster_entries SET claimed_by_user_id = ? WHERE id = ?",
        (user["id"], entry["id"]),
    )
    conn.commit()
    sent = _issue_verification(conn, settings, user, display_name)
    # "created" tells the student the account exists but no email is coming, so
    # they ask the instructor instead of waiting for a message that never arrives.
    return {"status": "verification_sent" if sent else "created", "email": email}


@router.post("/resend", dependencies=[Depends(csrf_check)])
def resend_verification(
    body: ResendRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Same response whether or not the address has a pending account, so this
    cannot be used to discover who has registered."""
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND is_active = 1", (body.email.strip(),)
    ).fetchone()
    if user is not None and user["email_verified_at"] is None:
        last = conn.execute(
            "SELECT MAX(created_at) AS t FROM email_verifications WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["t"]
        if last is None or time.time() - last >= settings.resend_cooldown_seconds:
            _issue_verification(conn, settings, user, user["username"])
    return {"status": "verification_sent"}


@router.get("/verify")
def verify_email(
    token: str,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    """Opening the link confirms the address AND signs the student in."""
    now = time.time()
    row = conn.execute(
        """SELECT * FROM email_verifications
           WHERE token_hash = ? AND used = 0 AND expires_at > ?""",
        (hash_session_token(token), now),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    conn.execute(
        "UPDATE email_verifications SET used = 1 WHERE token_hash = ?", (row["token_hash"],)
    )
    conn.execute(
        "UPDATE users SET email_verified_at = ? WHERE id = ? AND email_verified_at IS NULL",
        (now, row["user_id"]),
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    _start_session(response, conn, user["id"], settings)
    return _me(conn, user, settings)


@router.post("/login", dependencies=[Depends(csrf_check)])
def login(
    body: LoginRequest,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    ident = body.username.strip()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND is_active = 1", (ident,)
    ).fetchone()
    if user is None:
        # Instructors, and students created under the retired class-code flow,
        # have no email and still sign in by username.
        user = conn.execute(
            """SELECT * FROM users
               WHERE username = ? AND email IS NULL AND is_active = 1""",
            (ident,),
        ).fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="bad_credentials")
    if user["email"] is not None and user["email_verified_at"] is None:
        raise HTTPException(status_code=403, detail="email_not_verified")
    _start_session(response, conn, user["id"], settings)
    return _me(conn, user, settings)


# ── forgotten passwords ──────────────────────────────────────────────────


@router.post("/forgot", dependencies=[Depends(csrf_check)])
def forgot_password(
    body: ForgotPasswordRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Always answers the same way, whether or not the address has an account:
    the response must not reveal who is registered. A cooldown stops the
    endpoint being used to spam someone's inbox."""
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND is_active = 1", (body.email.strip(),)
    ).fetchone()
    if user is not None:
        last = conn.execute(
            "SELECT MAX(created_at) AS t FROM password_resets WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["t"]
        if last is None or time.time() - last >= settings.resend_cooldown_seconds:
            token = new_session_token()
            now = time.time()
            conn.execute(
                """INSERT INTO password_resets (token_hash, user_id, created_at, expires_at)
                   VALUES (?,?,?,?)""",
                (
                    hash_session_token(token), user["id"], now,
                    now + settings.reset_ttl_hours * 3600,
                ),
            )
            conn.commit()
            url = f"{settings.app_base_url.rstrip('/')}/reset?token={token}"
            try:
                mailer_mod.get_mailer(settings).send_password_reset(
                    user["email"], user["username"], url, int(settings.reset_ttl_hours)
                )
            except Exception:
                log.exception(
                    "Could not send the password reset email to %s. Link: %s",
                    user["email"], url,
                )
    return {"status": "reset_sent"}


@router.post("/reset", dependencies=[Depends(csrf_check)])
def reset_password(
    body: ResetPasswordRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Consumes the link, sets the new password, and revokes every existing
    session for that account — if the reset was prompted by someone else having
    access, that access ends here."""
    now = time.time()
    row = conn.execute(
        """SELECT * FROM password_resets
           WHERE token_hash = ? AND used = 0 AND expires_at > ?""",
        (hash_session_token(body.token), now),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    conn.execute(
        "UPDATE password_resets SET used = 1 WHERE token_hash = ?", (row["token_hash"],)
    )
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(body.password), row["user_id"]),
    )
    conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (row["user_id"],))
    # Opening a link sent to the address also proves the address, so a student
    # who never confirmed can recover this way instead of being stuck.
    conn.execute(
        "UPDATE users SET email_verified_at = ? WHERE id = ? AND email_verified_at IS NULL",
        (now, row["user_id"]),
    )
    conn.commit()
    return {"status": "password_reset"}


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
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    return _me(conn, user, settings)

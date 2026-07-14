"""Passwords, session tokens, opaque student tokens, class codes."""

import hashlib
import secrets
import sqlite3

import bcrypt

# Class codes avoid ambiguous glyphs (0/O, 1/I/L).
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password longer than 72 bytes")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_class_code() -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"SEC-{body}"


def new_opaque_token(conn: sqlite3.Connection) -> str:
    """Mint a unique 'student_a4f9c2'-shaped token (the documented shape)."""
    for _ in range(64):
        token = "student_" + secrets.token_hex(3)
        row = conn.execute(
            "SELECT 1 FROM users WHERE opaque_token = ?", (token,)
        ).fetchone()
        if row is None:
            return token
    raise RuntimeError("could not mint a unique opaque token")

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server import db as dbmod  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import Settings  # noqa: E402
from server.security import hash_password, new_class_code  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "server_data", enable_llm=False)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(settings, app):
    """Instructor 'prof'/'prof-pass-123', one section, its class code."""
    conn = dbmod.connect(settings.db_path)
    try:
        existing_user = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", ("prof",)
        ).fetchone()
        if existing_user is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at)"
                " VALUES ('prof', ?, 'instructor', ?)",
                (hash_password("prof-pass-123"), time.time()),
            )

        existing_section = conn.execute(
            "SELECT class_code FROM sections WHERE name = ? LIMIT 1", ("Section A",)
        ).fetchone()
        if existing_section is None:
            code = new_class_code()
            conn.execute(
                "INSERT INTO sections (name, class_code, created_at) VALUES ('Section A', ?, ?)",
                (code, time.time()),
            )
        else:
            code = existing_section["class_code"]

        conn.commit()
    finally:
        conn.close()
    conn = dbmod.connect(settings.db_path)
    try:
        section_id = conn.execute(
            "SELECT id FROM sections WHERE name = 'Section A'"
        ).fetchone()["id"]
    finally:
        conn.close()
    return {"class_code": code, "section_id": section_id}


def register_student(client, seeded, username="anna", password="hunter2-long"):
    """Full roster flow, API-only, as a student would experience it:
    the instructor adds the address to the section roster, the student
    registers, and the account is activated. Leaves the client signed in as
    that student, as the old class-code helper did.

    Activation goes through the instructor's manual-verify action rather than
    the emailed link so this helper does not need access to the mailer; the
    link itself is covered in test_roster_auth.py.
    """
    email = f"{username.lower().replace(' ', '.')}@nyu.edu"
    section_id = seeded["section_id"]
    csv = f"email,netid,full_name\n{email},{username.lower()},{username}\n".encode("utf-8")

    login(client, "prof", "prof-pass-123")
    r = client.post(
        f"/api/instructor/sections/{section_id}/roster",
        files={"file": ("roster.csv", csv, "text/csv")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 200, r.text
    client.post("/api/auth/logout", json={})

    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 202, r.text

    login(client, "prof", "prof-pass-123")
    entry = [
        e for e in client.get(f"/api/instructor/sections/{section_id}/roster").json()
        if e["email"] == email
    ][0]
    r = client.post(f"/api/instructor/roster/{entry['id']}/verify", json={})
    assert r.status_code == 200, r.text
    client.post("/api/auth/logout", json={})

    return login(client, email, password)


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()

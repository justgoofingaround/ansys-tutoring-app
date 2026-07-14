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
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at)"
            " VALUES ('prof', ?, 'instructor', ?)",
            (hash_password("prof-pass-123"), time.time()),
        )
        code = new_class_code()
        conn.execute(
            "INSERT INTO sections (name, class_code, created_at) VALUES ('Section A', ?, ?)",
            (code, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"class_code": code}


def register_student(client, seeded, username="anna", password="hunter2-long"):
    r = client.post(
        "/api/auth/register",
        json={"class_code": seeded["class_code"], "username": username, "password": password},
    )
    assert r.status_code == 201, r.text
    return r.json()


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()

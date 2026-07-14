from .conftest import login, register_student


def test_register_login_me_flow(client, seeded):
    me = register_student(client, seeded)
    assert me["role"] == "student"
    assert me["opaque_token"].startswith("student_")
    assert me["section"] == "Section A"

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "anna"

    r = client.post("/api/auth/logout", json={})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    me2 = login(client, "anna", "hunter2-long")
    assert me2["opaque_token"] == me["opaque_token"]


def test_register_rejects_bad_class_code(client, seeded):
    r = client.post(
        "/api/auth/register",
        json={"class_code": "SEC-NOPE99", "username": "bob", "password": "long-enough-pw"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_class_code"


def test_register_rejects_duplicate_username_case_insensitive(client, seeded):
    register_student(client, seeded, username="Casey")
    r = client.post(
        "/api/auth/register",
        json={"class_code": seeded["class_code"], "username": "casey", "password": "long-enough-pw"},
    )
    assert r.status_code == 409


def test_login_rejects_bad_password(client, seeded):
    register_student(client, seeded)
    r = client.post("/api/auth/login", json={"username": "anna", "password": "wrong-password"})
    assert r.status_code == 401


def test_instructor_login_and_section_management(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post("/api/instructor/sections", json={"name": "Section B"})
    assert r.status_code == 201
    body = r.json()
    assert body["class_code"].startswith("SEC-")

    r = client.get("/api/instructor/sections")
    names = [s["name"] for s in r.json()]
    assert names == ["Section A", "Section B"]

    r = client.post(f"/api/instructor/sections/{body['id']}/regenerate-code", json={})
    assert r.status_code == 200
    assert r.json()["class_code"] != body["class_code"]


def test_student_cannot_use_instructor_endpoints(client, seeded):
    register_student(client, seeded)
    assert client.get("/api/instructor/sections").status_code == 403


def test_opaque_token_header_authenticates_like_overlay(client, seeded):
    me = register_student(client, seeded)
    token = me["opaque_token"]
    client.post("/api/auth/logout", json={})

    r = client.get("/api/auth/me", headers={"X-Session-Token": token})
    assert r.status_code == 200
    assert r.json()["username"] == "anna"


def test_csrf_rejects_form_content_type(client, seeded):
    # A cross-site HTML form can send urlencoded bodies without preflight;
    # our state-changing routes must reject that shape.
    r = client.post(
        "/api/auth/login",
        data={"username": "prof", "password": "prof-pass-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 403

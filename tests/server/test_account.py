"""Changing your own password while signed in.

The emailed reset flow is covered in test_roster_auth.py; this is the
signed-in path, where the current password is the proof instead of a link.
"""

from .conftest import login, register_student


def _change(client, current, new):
    return client.post(
        "/api/auth/password", json={"current_password": current, "password": new}
    )


def test_student_changes_password_and_the_new_one_works(client, seeded):
    register_student(client, seeded, "stu_pw", "old-pass-1234")
    assert _change(client, "old-pass-1234", "new-pass-5678").status_code == 200

    client.post("/api/auth/logout", json={})
    email = "stu_pw@nyu.edu"
    assert client.post(
        "/api/auth/login", json={"username": email, "password": "old-pass-1234"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": email, "password": "new-pass-5678"}
    ).status_code == 200


def test_wrong_current_password_is_refused(client, seeded):
    register_student(client, seeded, "stu_pw2", "old-pass-1234")
    r = _change(client, "not-my-password", "new-pass-5678")
    assert r.status_code == 403 and r.json()["detail"] == "wrong_password"


def test_new_password_must_differ_and_be_long_enough(client, seeded):
    register_student(client, seeded, "stu_pw3", "old-pass-1234")
    assert _change(client, "old-pass-1234", "old-pass-1234").status_code == 400
    assert _change(client, "old-pass-1234", "short").status_code == 422


def test_the_session_that_changed_it_stays_signed_in(client, seeded):
    """Logging the student out of the page they are standing on would be a
    surprise; other sessions are a different matter — see below."""
    register_student(client, seeded, "stu_pw4", "old-pass-1234")
    _change(client, "old-pass-1234", "new-pass-5678")
    assert client.get("/api/auth/me").status_code == 200


def test_other_sessions_are_revoked(client, app, seeded):
    """A password change is how you end someone else's session on a lab PC."""
    from fastapi.testclient import TestClient

    register_student(client, seeded, "stu_pw5", "old-pass-1234")
    with TestClient(app) as other:
        login(other, "stu_pw5@nyu.edu", "old-pass-1234")
        assert other.get("/api/auth/me").status_code == 200

        _change(client, "old-pass-1234", "new-pass-5678")
        assert other.get("/api/auth/me").status_code == 401


def test_instructor_can_change_their_own_password(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert _change(client, "prof-pass-123", "prof-pass-456").status_code == 200
    client.post("/api/auth/logout", json={})
    assert login(client, "prof", "prof-pass-456")["role"] == "instructor"


def test_signed_out_callers_are_rejected(client, seeded):
    assert _change(client, "whatever", "new-pass-5678").status_code == 401

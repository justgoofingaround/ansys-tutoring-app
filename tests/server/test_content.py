"""Tutorial store, content endpoints, events ingestion, progress, reports."""

import io
import time

from .conftest import login, register_student

GOOD_REPORT = """Project
Static Structural
Model
Material: Structural Steel
Solution
Total Deformation
Results
Directional Deformation maximum 0.00382 in
"""

BAD_REPORT = "Just some notes, nothing structured.\n"


def test_tut1_seeded_and_served(client, seeded):
    register_student(client, seeded)
    r = client.get("/api/tutorials")
    assert r.status_code == 200
    listing = r.json()
    assert len(listing) == 1
    t = listing[0]
    assert t["tutorial_id"] == "tut1_3d_bar"
    assert t["is_mandatory"] is True
    assert t["has_report_checks"] is True

    r = client.get("/api/tutorials/tut1_3d_bar")
    body = r.json()
    assert body["_meta"]["version"] == 1
    assert body["sections"]
    assert body["runtime_steps"]


def test_tutorials_require_auth(client, seeded):
    assert client.get("/api/tutorials").status_code == 401


def test_overlay_token_can_fetch_tutorials(client, seeded):
    me = register_student(client, seeded)
    client.post("/api/auth/logout", json={})
    r = client.get("/api/tutorials", headers={"X-Session-Token": me["opaque_token"]})
    assert r.status_code == 200


def test_dashboard_not_started_then_events_progress(client, seeded):
    register_student(client, seeded)
    r = client.get("/api/student/dashboard")
    assert r.status_code == 200
    card = r.json()["tutorials"][0]
    assert card["status"] == "not_started"
    assert card["percent"] == 0
    assert card["steps_total"] == 20  # tut1 runtime_steps

    now = time.time()
    events = [
        {"tutorial_id": "tut1_3d_bar", "step_id": "wb_01_open",
         "action_type": "step_completed", "timestamp": now},
        {"tutorial_id": "tut1_3d_bar", "step_id": "wb_02_save_project",
         "action_type": "step_completed", "timestamp": now},
        {"tutorial_id": "tut1_3d_bar", "step_id": "wb_03_add_static_structural",
         "action_type": "verify_failed", "timestamp": now,
         "extra": {"failed_check": "ocr_text_present"}},
        {"tutorial_id": "tut1_3d_bar", "step_id": "wb_03_add_static_structural",
         "action_type": "verify_failed", "timestamp": now},
        {"tutorial_id": "tut1_3d_bar", "step_id": "wb_03_add_static_structural",
         "action_type": "verify_failed", "timestamp": now},
    ]
    r = client.post("/api/events/action_events", json=events)
    assert r.status_code == 202 and r.json()["accepted"] == 5

    detail = client.get("/api/student/tutorials/tut1_3d_bar").json()
    assert detail["status"] == "in_progress"
    assert detail["steps_completed"] == 2
    by_id = {s["step_id"]: s for sec in detail["sections"] for s in sec["steps"]}
    assert by_id["wb_01_open"]["status"] == "completed"
    assert by_id["wb_03_add_static_structural"]["status"] == "struggling"
    assert by_id["wb_03_add_static_structural"]["fail_count"] == 3
    assert by_id["wb_04_select_geometry"]["status"] == "not_started"
    # sc_/ed_ steps aren't in runtime_steps -> not shown
    assert "sc_01_open_geometry" not in by_id


def test_event_token_spoofing_is_overwritten(client, seeded, settings):
    me = register_student(client, seeded)
    r = client.post(
        "/api/events/action_events",
        json=[{"session_token": "student_forged", "tutorial_id": "tut1_3d_bar",
               "step_id": "wb_01_open", "action_type": "step_started",
               "timestamp": time.time()}],
    )
    assert r.status_code == 202
    from server import db as dbmod
    conn = dbmod.connect(settings.db_path)
    try:
        row = conn.execute("SELECT session_token FROM action_events").fetchone()
        assert row["session_token"] == me["opaque_token"]
    finally:
        conn.close()


def test_instructor_cannot_post_events(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/events/action_events",
        json=[{"tutorial_id": "t", "step_id": "s", "action_type": "a", "timestamp": 0}],
    )
    assert r.status_code == 403


def _upload(client, content: str, filename="report.txt"):
    return client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": (filename, io.BytesIO(content.encode("utf-8")), "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )


def test_report_upload_pass_and_fail(client, seeded):
    register_student(client, seeded)

    r = _upload(client, BAD_REPORT)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["score"] < body["total"]

    r = _upload(client, GOOD_REPORT)
    body = r.json()
    assert body["ok"] is True
    assert body["score"] == body["total"] == 4
    names = {c["name"] for c in body["checks"]}
    assert "expected_result" in names

    # A passing report satisfies the report milestone, but tut1 also has a
    # quiz milestone now — completion needs both (see test_quizzes).
    card = client.get("/api/student/dashboard").json()["tutorials"][0]
    assert card["status"] == "in_progress"
    assert card["report"]["ok"] is True

    history = client.get("/api/tutorials/tut1_3d_bar/reports/mine").json()
    assert len(history) == 2
    assert history[0]["ok"] is True


def test_report_upload_rejects_bad_extension(client, seeded):
    register_student(client, seeded)
    r = client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": ("report.exe", io.BytesIO(b"x"), "application/octet-stream")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 400


def test_report_upload_requires_csrf_header(client, seeded):
    register_student(client, seeded)
    r = client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": ("report.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert r.status_code == 403


def test_faq_endpoints_empty(client, seeded):
    register_student(client, seeded)
    assert client.get("/api/tutorials/tut1_3d_bar/faqs").json() == []
    assert client.get("/api/tutorials/tut1_3d_bar/steps/wb_01_open/faqs").json() == []


def test_step_reference_images_served(client, seeded):
    r = client.get("/tutorial-images/tut1/me_04_generate_mesh.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_web_marked_step_shows_as_completed(client, seeded):
    """The in-app runner's 'Mark step complete' -> tick flow."""
    import time as _time
    register_student(client, seeded)
    r = client.post(
        "/api/events/action_events",
        json=[{"tutorial_id": "tut1_3d_bar", "step_id": "wb_01_open",
               "action_type": "step_completed", "timestamp": _time.time()}],
    )
    assert r.status_code == 202
    detail = client.get("/api/student/tutorials/tut1_3d_bar").json()
    first = detail["sections"][0]["steps"][0]
    assert first["step_id"] == "wb_01_open"
    assert first["status"] == "completed"
    assert detail["steps_completed"] == 1

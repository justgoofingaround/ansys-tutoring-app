"""Instructor core: progress matrix, activity feed, quiz stats, and the
tutorial library upload -> validate -> publish flow."""

import io
import json
import time
from pathlib import Path

from .conftest import login, register_student

REPO_ROOT = Path(__file__).resolve().parents[2]
QUIZ_ID = "quiz_tut1_3d_bar"

GOOD_REPORT = """Project
Static Structural
Model
Material: Structural Steel
Solution
Total Deformation
Results
Directional Deformation maximum 0.00382 in
"""


def _student_activity(client, seeded):
    """anna: 2 steps + passing report + quiz attempt. ben: untouched."""
    register_student(client, seeded)  # anna
    now = time.time()
    client.post(
        "/api/events/action_events",
        json=[
            {"tutorial_id": "tut1_3d_bar", "step_id": "wb_01_open",
             "action_type": "step_completed", "timestamp": now},
            {"tutorial_id": "tut1_3d_bar", "step_id": "wb_02_save_project",
             "action_type": "step_completed", "timestamp": now},
        ],
    )
    client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": ("report.txt", io.BytesIO(GOOD_REPORT.encode()), "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )
    client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [0] * 6})
    client.post("/api/auth/logout", json={})
    register_student(client, seeded, username="ben", password="bens-password")
    client.post("/api/auth/logout", json={})


def test_progress_matrix(client, seeded):
    _student_activity(client, seeded)
    login(client, "prof", "prof-pass-123")
    body = client.get("/api/instructor/progress").json()

    assert [t["tutorial_id"] for t in body["tutorials"]] == ["tut1_3d_bar"]
    by_name = {s["username"]: s for s in body["students"]}
    assert set(by_name) == {"anna", "ben"}
    anna = by_name["anna"]["cells"]["tut1_3d_bar"]
    ben = by_name["ben"]["cells"]["tut1_3d_bar"]
    assert anna["report_ok"] is True and anna["quiz_attempts"] == 1
    assert anna["status"] == "completed"
    assert ben["status"] == "not_started" and ben["percent"] == 0

    tiles = body["tiles"]
    assert tiles["students"] == 2
    assert tiles["reports_passed"] == 1
    assert tiles["quiz_avg"] is not None


def test_activity_feed_merges_sources(client, seeded):
    _student_activity(client, seeded)
    login(client, "prof", "prof-pass-123")
    feed = client.get("/api/instructor/activity?limit=10").json()
    kinds = {e["kind"] for e in feed}
    assert kinds == {"event", "report", "quiz"}
    assert all(e["username"] == "anna" for e in feed)
    assert all(e["tutorial_title"].startswith("Tutorial 1") for e in feed)
    # newest first
    ts = [e["timestamp"] for e in feed]
    assert ts == sorted(ts, reverse=True)


def test_quiz_stats_histogram(client, seeded):
    _student_activity(client, seeded)
    login(client, "prof", "prof-pass-123")
    stats = client.get("/api/instructor/quiz-stats").json()
    assert len(stats) == 1
    s = stats[0]
    assert s["quiz_id"] == QUIZ_ID and s["total_questions"] == 6
    assert s["students"] == 1 and s["attempts"] == 1
    # anna answered all 0s -> some correct count k; histogram has exactly one student
    assert sum(b["count"] for b in s["histogram"]) == 1
    assert len(s["histogram"]) == 7  # 0..6 correct


def test_library_upload_validate_publish(client, seeded, settings):
    login(client, "prof", "prof-pass-123")

    # invalid: not a tutorial at all
    r = client.post(
        "/api/instructor/tutorials",
        files={"file": ("bad.json", io.BytesIO(b'{"nope": true}'), "application/json")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 422
    findings = r.json()["detail"]["findings"]
    assert any(f["severity"] == "error" for f in findings)

    # valid: tut1's content under a new id -> stored as an UNPUBLISHED draft
    data = json.loads(
        (REPO_ROOT / "mock_server" / "data" / "tut1.json").read_text(encoding="utf-8")
    )
    data["tutorial_id"] = "tut_test_upload"
    data["title"] = "Uploaded test tutorial"
    r = client.post(
        "/api/instructor/tutorials",
        files={"file": ("tut_test.json", io.BytesIO(json.dumps(data).encode()), "application/json")},
        data={"product": "mechanical", "is_mandatory": "false"},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 201, r.text
    version = r.json()["version"]

    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    assert lib["tut_test_upload"]["published_version"] is None  # draft
    assert lib["tut1_3d_bar"]["published_version"] == 1

    # students can't see the draft
    client.post("/api/auth/logout", json={})
    register_student(client, seeded)
    ids = {t["tutorial_id"] for t in client.get("/api/tutorials").json()}
    assert "tut_test_upload" not in ids
    client.post("/api/auth/logout", json={})

    # publish -> students see it
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/instructor/tutorials/tut_test_upload/publish", json={"version": version}
    )
    assert r.status_code == 200
    client.post("/api/auth/logout", json={})
    login(client, "anna", "hunter2-long")
    ids = {t["tutorial_id"] for t in client.get("/api/tutorials").json()}
    assert "tut_test_upload" in ids


def test_publish_unknown_version_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post("/api/instructor/tutorials/tut1_3d_bar/publish", json={"version": 99})
    assert r.status_code == 404


def test_mandatory_toggle(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/instructor/tutorials/tut1_3d_bar/settings", json={"is_mandatory": False}
    )
    assert r.status_code == 200 and r.json()["is_mandatory"] is False


def _quiz_upload(client, data: dict):
    return client.post(
        "/api/instructor/quizzes",
        files={"file": ("quiz.json", io.BytesIO(json.dumps(data).encode()), "application/json")},
        headers={"X-Requested-With": "fetch"},
    )


def test_quiz_upload_validation_errors(client, seeded):
    login(client, "prof", "prof-pass-123")

    r = client.post(
        "/api/instructor/quizzes",
        files={"file": ("bad.json", io.BytesIO(b"not json"), "application/json")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 422

    r = _quiz_upload(client, {
        "quiz_id": "quiz_x", "tutorial_id": "no_such_tutorial", "title": "X",
        "questions": [
            {"text": "Q?", "options": ["a", "b"], "correct_index": 5},
            {"text": "", "options": ["only-one"], "correct_index": 0},
        ],
    })
    assert r.status_code == 422
    messages = " | ".join(f["message"] for f in r.json()["detail"]["findings"])
    assert "does not exist" in messages
    assert "out of range" in messages
    assert "at least 2" in messages


def test_quiz_upload_and_replace(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = _quiz_upload(client, {
        "quiz_id": QUIZ_ID,  # replaces the seeded tut1 quiz
        "tutorial_id": "tut1_3d_bar",
        "title": "Tutorial 1 — new quiz",
        "questions": [
            {"text": "2+2?", "options": ["3", "4"], "correct_index": 1,
             "concept_tag": "math", "explanation": "It is 4."},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["replaced"] is True and body["questions"] == 1
    assert any("replaced" in w["message"] for w in body["warnings"])

    quiz = client.get(f"/api/quizzes/{QUIZ_ID}").json()
    assert quiz["title"] == "Tutorial 1 — new quiz"
    assert len(quiz["questions"]) == 1

    # brand-new quiz for the same tutorial relinks it
    r = _quiz_upload(client, {
        "quiz_id": "quiz_tut1_v2", "tutorial_id": "tut1_3d_bar", "title": "V2",
        "questions": [{"text": "Q", "options": ["a", "b"], "correct_index": 0}],
    })
    assert r.status_code == 201 and r.json()["replaced"] is False
    client.post("/api/auth/logout", json={})
    register_student(client, seeded)
    detail = client.get("/api/student/tutorials/tut1_3d_bar").json()
    assert detail["quiz"]["quiz_id"] == "quiz_tut1_v2"


def test_student_cannot_upload_quiz(client, seeded):
    register_student(client, seeded)
    r = _quiz_upload(client, {"quiz_id": "q", "tutorial_id": "t", "title": "t", "questions": []})
    assert r.status_code == 403


def test_students_cannot_reach_instructor_endpoints(client, seeded):
    register_student(client, seeded)
    for path in ("/api/instructor/progress", "/api/instructor/activity",
                 "/api/instructor/quiz-stats", "/api/instructor/tutorials"):
        assert client.get(path).status_code == 403

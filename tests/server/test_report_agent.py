"""Reports checked on the instructor desktop instead of on the hub.

The hub has no GPU, so with REPORT_CHECKER=agent it only takes custody of the
file: a checker on the instructor's desktop claims the work, runs the rubric
there and posts the result back. These tests stand in for that checker.
"""

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings

from .conftest import login, register_student

TUT = "tut1_3d_bar"
TOKEN = "agent-secret-123"
REPORT = b"""Static Structural
Solution
Results
Total Deformation
Structural Steel
Directional Deformation: 0.00382 in
"""


@pytest.fixture()
def agent_client(tmp_path):
    """A hub that queues reports instead of grading them."""
    s = Settings(
        data_dir=tmp_path / "agent", enable_llm=False, smtp_host=None,
        report_checker="agent", agent_token=TOKEN,
        instructor_username="prof", instructor_password="prof-pass-123",
    )
    with TestClient(create_app(s)) as c:
        yield c


def _seeded_section(client):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    client.post("/api/auth/logout", json={})
    return {"section_id": section_id, "class_code": None}


def _submit(client, seeded, name="stu_rep"):
    register_student(client, seeded, name, "pw-eight-chars")
    r = client.post(
        f"/api/tutorials/{TUT}/report",
        files={"file": ("report.txt", REPORT, "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _agent(client, method, path, **kw):
    return getattr(client, method)(path, headers={"X-Agent-Token": TOKEN}, **kw)


# --- queueing ---------------------------------------------------------------


def test_upload_is_queued_not_graded(agent_client):
    body = _submit(agent_client, _seeded_section(agent_client))
    assert body["status"] == "pending"
    assert body["score"] == 0 and body["checks"] == []

    mine = agent_client.get(f"/api/tutorials/{TUT}/reports/mine").json()
    assert mine[0]["status"] == "pending"


def test_hub_still_grades_inline_by_default(client, seeded):
    """The default deployment is unchanged — no agent, no queue."""
    body = _submit(client, seeded)
    assert body["status"] == "checked"
    assert body["total"] > 0


# --- the desktop checker's side ---------------------------------------------


def test_claim_download_and_post_back(agent_client):
    sub = _submit(agent_client, _seeded_section(agent_client))
    sid = sub["submission_id"]

    job = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    assert job["submission_id"] == sid
    assert job["filename"] == "report.txt"
    assert job["report_checks"], "the rubric travels with the job"

    f = _agent(agent_client, "get", f"/api/agent/reports/{sid}/file")
    assert f.status_code == 200 and b"Structural Steel" in f.content

    r = _agent(agent_client, "post", f"/api/agent/reports/{sid}/result", json={
        "ok": True, "score": 4, "total": 4,
        "checks": [{"name": "sections", "ok": True, "message": "all present"}],
        "feedback": "Looks right.",
    })
    assert r.status_code == 200 and r.json()["status"] == "checked"

    mine = agent_client.get(f"/api/tutorials/{TUT}/reports/mine").json()[0]
    assert mine["status"] == "checked" and mine["ok"] and mine["score"] == 4
    assert mine["feedback"] == "Looks right."


def test_a_claimed_report_is_not_handed_out_twice(agent_client):
    _submit(agent_client, _seeded_section(agent_client))
    first = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    second = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    assert first["submission_id"]
    assert second == {}


def test_empty_queue_returns_nothing(agent_client):
    _seeded_section(agent_client)
    assert _agent(agent_client, "post", "/api/agent/reports/claim").json() == {}


def test_a_checker_that_cannot_read_the_file_reports_failure(agent_client):
    """A broken upload must not look like a zero the student earned."""
    sub = _submit(agent_client, _seeded_section(agent_client))
    sid = sub["submission_id"]
    _agent(agent_client, "post", "/api/agent/reports/claim")
    _agent(agent_client, "post", f"/api/agent/reports/{sid}/result",
           json={"failed": True, "feedback": "The checker could not read this file."})

    mine = agent_client.get(f"/api/tutorials/{TUT}/reports/mine").json()[0]
    assert mine["status"] == "failed" and not mine["ok"]


def test_stale_claims_go_back_in_the_queue(agent_client, tmp_path):
    """The desktop was closed mid-check; the work must not be stranded."""
    import sqlite3
    sub = _submit(agent_client, _seeded_section(agent_client))
    _agent(agent_client, "post", "/api/agent/reports/claim")

    db = sqlite3.connect(tmp_path / "agent" / "app.db")
    db.execute("UPDATE report_submissions SET claimed_at = 0 WHERE id = ?",
               (sub["submission_id"],))
    db.commit()
    db.close()

    again = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    assert again["submission_id"] == sub["submission_id"]


# --- the secret -------------------------------------------------------------


def test_agent_routes_need_the_token(agent_client):
    _submit(agent_client, _seeded_section(agent_client))
    assert agent_client.post("/api/agent/reports/claim").status_code == 401
    assert agent_client.post(
        "/api/agent/reports/claim", headers={"X-Agent-Token": "wrong"}
    ).status_code == 401


def test_a_hub_with_no_token_configured_refuses_every_agent_call(client, seeded):
    """An unconfigured hub must not hand student work to anyone who asks."""
    assert client.post(
        "/api/agent/reports/claim", headers={"X-Agent-Token": "anything"}
    ).status_code == 401


# --- what the instructor sees -----------------------------------------------


def test_status_reports_queue_depth(agent_client):
    seeded = _seeded_section(agent_client)
    login(agent_client, "prof", "prof-pass-123")
    assert agent_client.get("/api/agent/status").json()["pending"] == 0
    agent_client.post("/api/auth/logout", json={})

    _submit(agent_client, seeded, "stu_q")
    agent_client.post("/api/auth/logout", json={})

    login(agent_client, "prof", "prof-pass-123")
    body = agent_client.get("/api/agent/status").json()
    assert body["pending"] == 1 and body["checker_last_seen"] is None

    _agent(agent_client, "post", "/api/agent/reports/claim")
    body = agent_client.get("/api/agent/status").json()
    assert body["in_progress"] == 1 and body["checker_last_seen"] is not None


# --- the grading app on the instructor's desktop ---------------------------


def test_the_agent_can_list_reports_with_names(agent_client):
    """The grading app is a gradebook, so it needs names. This is the one
    place the agent token sees them, and it still sees nothing without it."""
    seeded = _seeded_section(agent_client)
    _submit(agent_client, seeded, "stu_named")
    agent_client.post("/api/auth/logout", json={})

    assert agent_client.get("/api/agent/reports").status_code == 401

    rows = _agent(agent_client, "get", "/api/agent/reports").json()
    assert rows[0]["student"] == "stu_named"
    assert rows[0]["tutorial_id"] == TUT
    assert "stored_path" not in rows[0]  # the file is reachable only by its route


def test_the_agent_can_write_feedback_the_student_sees(agent_client):
    seeded = _seeded_section(agent_client)
    sub = _submit(agent_client, seeded, "stu_fb")
    sid = sub["submission_id"]

    r = _agent(agent_client, "post", f"/api/agent/reports/{sid}/feedback",
               json={"feedback": "Mesh is too coarse near the fillet."})
    assert r.status_code == 200, r.text

    detail = agent_client.get(f"/api/student/tutorials/{TUT}").json()
    seen = [s for s in detail["report_submissions"] if s["submission_id"] == sid][0]
    assert seen["instructor_feedback"] == "Mesh is too coarse near the fillet."


def test_claiming_one_report_by_id_works_on_a_checked_one(agent_client):
    """"Run the AI review again" on a report the rubric already scored."""
    seeded = _seeded_section(agent_client)
    sid = _submit(agent_client, seeded, "stu_again")["submission_id"]
    job = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    _agent(agent_client, "post", f"/api/agent/reports/{job['submission_id']}/result",
           json={"ok": True, "score": 4, "total": 4, "checks": [], "feedback": "fine"})

    again = _agent(agent_client, "post", f"/api/agent/reports/{sid}/claim")
    assert again.status_code == 200, again.text
    assert again.json()["submission_id"] == sid
    assert again.json()["report_checks"]  # the rubric travels with the job

    assert _agent(agent_client, "post", "/api/agent/reports/9999/claim").status_code == 404


def test_config_tells_the_app_whether_ai_is_permitted(agent_client):
    """The hub owns the switch, so the app greys the button out rather than
    letting the instructor click and read a failure."""
    assert agent_client.get("/api/agent/config").status_code == 401
    assert _agent(agent_client, "get", "/api/agent/config").json()["ai_enabled"] is False


def test_status_counts_what_needs_the_instructor(agent_client):
    """The sidebar badge. A report that passed needs nobody, so counting it
    would leave a number the instructor can never clear; one that failed the
    rubric and has no feedback yet is exactly the work."""
    seeded = _seeded_section(agent_client)
    sub = _submit(agent_client, seeded, "stu_badge")
    agent_client.post("/api/auth/logout", json={})

    login(agent_client, "prof", "prof-pass-123")
    assert agent_client.get("/api/agent/status").json()["needs_review"] == 0  # still queued

    job = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    _agent(agent_client, "post", f"/api/agent/reports/{job['submission_id']}/result",
           json={"ok": False, "score": 1, "total": 4, "checks": [], "feedback": "thin"})
    body = agent_client.get("/api/agent/status").json()
    assert body["needs_review"] == 1
    assert body["now"] > 0  # the page dates last_seen against our clock, not the browser's

    agent_client.post(
        f"/api/instructor/reports/{sub['submission_id']}/feedback",
        json={"feedback": "Add the mesh statistics table."},
    )
    assert agent_client.get("/api/agent/status").json()["needs_review"] == 0


def test_a_passing_report_does_not_ask_for_attention(agent_client):
    seeded = _seeded_section(agent_client)
    _submit(agent_client, seeded, "stu_pass")
    agent_client.post("/api/auth/logout", json={})

    login(agent_client, "prof", "prof-pass-123")
    job = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    _agent(agent_client, "post", f"/api/agent/reports/{job['submission_id']}/result",
           json={"ok": True, "score": 4, "total": 4, "checks": [], "feedback": "good"})
    assert agent_client.get("/api/agent/status").json()["needs_review"] == 0


def test_status_is_for_the_instructor_only(agent_client):
    """The queue depth drives the instructor's Reports page. A student can do
    nothing with it, and left open it lets anyone probe the hub."""
    seeded = _seeded_section(agent_client)
    assert agent_client.get("/api/agent/status").status_code == 401

    register_student(agent_client, seeded, "stu_nosy", "pw-eight-chars")
    assert agent_client.get("/api/agent/status").status_code == 403


# --- the AI switch has to cross the machine boundary ------------------------


def test_claim_tells_the_checker_ai_is_off(agent_client):
    """The hub owns ENABLE_AI, but the model runs on the instructor's desktop.
    A checker sitting on a GPU must not write an AI review for a hub that has
    AI switched off, so the switch travels with the job."""
    _submit(agent_client, _seeded_section(agent_client))
    job = _agent(agent_client, "post", "/api/agent/reports/claim").json()
    assert job["ai_enabled"] is False


def test_claim_says_ai_is_on_when_the_hub_has_it_on(tmp_path):
    s = Settings(
        data_dir=tmp_path / "ai_on", enable_ai=True, enable_llm=True, smtp_host=None,
        report_checker="agent", agent_token=TOKEN,
        instructor_username="prof", instructor_password="prof-pass-123",
    )
    with TestClient(create_app(s)) as c:
        _submit(c, _seeded_section(c))
        job = c.post("/api/agent/reports/claim", headers={"X-Agent-Token": TOKEN}).json()
        assert job["ai_enabled"] is True


def test_report_ai_can_be_on_while_student_ai_stays_off(tmp_path):
    """The professor's desktop has the GPU; the hub has neither GPU nor index.

    ENABLE_REPORT_AI lets his checker run the model over a report without
    advertising Compass to students or opening the hub's AI import paths,
    which would fail on use.
    """
    s = Settings(
        data_dir=tmp_path / "report_ai", smtp_host=None,
        enable_ai=False, enable_report_ai=True,
        report_checker="agent", agent_token=TOKEN,
        instructor_username="prof", instructor_password="prof-pass-123",
    )
    with TestClient(create_app(s)) as c:
        _submit(c, _seeded_section(c))
        job = c.post("/api/agent/reports/claim", headers={"X-Agent-Token": TOKEN}).json()
        assert job["ai_enabled"] is True, "the desktop may use its model"

        # ...while nothing student-facing changed
        assert c.get("/api/auth/me").json()["ai_enabled"] is False
        # the chatbot router is not mounted at all, so its routes 404
        assert c.get("/api/chatbot/consent").status_code == 404


def test_neither_switch_means_no_model(tmp_path):
    s = Settings(
        data_dir=tmp_path / "no_ai", smtp_host=None,
        report_checker="agent", agent_token=TOKEN,
        instructor_username="prof", instructor_password="prof-pass-123",
    )
    with TestClient(create_app(s)) as c:
        _submit(c, _seeded_section(c))
        job = c.post("/api/agent/reports/claim", headers={"X-Agent-Token": TOKEN}).json()
        assert job["ai_enabled"] is False

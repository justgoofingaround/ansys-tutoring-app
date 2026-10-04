"""The ENABLE_AI kill switch (NYU security review): with AI off — the default —
no generation path is reachable, while every non-AI feature keeps working.

The conftest `settings` fixture leaves enable_ai at its default (False), so the
shared `client`/`seeded` fixtures here are already an AI-disabled deployment.
"""

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings

from .conftest import login, register_student


# --- the switch itself ------------------------------------------------------


def test_disabled_by_default():
    """A deployment that never sets ENABLE_AI gets no AI at all."""
    s = Settings(data_dir="unused")
    assert s.enable_ai is False
    assert s.enable_llm is False


def test_stray_api_key_cannot_re_enable_generation(tmp_path):
    """Misconfiguration case: CHATBOT_API_KEY present but AI off. The key is
    dropped, so neither CloudApiEngine nor the PDF cloud fallback can run."""
    s = Settings(data_dir=tmp_path / "d", chatbot_api_key="sk-should-be-ignored")
    assert s.chatbot_api_key is None


def test_enable_ai_restores_the_llm_gate(tmp_path):
    """Reversibility: the flag is the only thing standing between the pilot
    build and a working AI build."""
    s = Settings(data_dir=tmp_path / "d", enable_ai=True, enable_llm=True)
    assert s.enable_llm is True


# --- student-facing surfaces ------------------------------------------------


def test_compass_routes_are_not_mounted(app, client, seeded):
    """Not merely erroring: the chatbot endpoints are never registered.

    Asserted against the route table because a GET to an unknown path is
    swallowed by the SPA catch-all (which serves index.html); the POST the
    overlay/SPA actually uses has no such fallback."""
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/api/chatbot")]
    register_student(client, seeded, "stu_ai", "pw-eight-chars")
    r = client.post("/api/chatbot/query", json={"question": "mesh?", "stream": False})
    assert r.status_code in (404, 405)


def test_me_reports_ai_disabled(client, seeded):
    """The SPA hides Compass, PDF import and FAQ drafting off this flag."""
    register_student(client, seeded, "stu_flag", "pw-eight-chars")
    assert client.get("/api/auth/me").json()["ai_enabled"] is False


# --- instructor-facing surfaces ---------------------------------------------


def test_pdf_conversion_refused(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/instructor/tutorials/from-pdf",
        files={"file": ("t.pdf", b"%PDF-1.4 not a real pdf", "application/pdf")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 503 and r.json()["detail"] == "ai_disabled"


# --- the non-AI app still works ---------------------------------------------


def test_report_check_still_runs_without_ai(client, seeded):
    """Rubric scoring is deterministic and must survive the AI being off; only
    the narrative review disappears."""
    register_student(client, seeded, "stu_rep", "pw-eight-chars")
    report = (
        "Static Structural\nSolution\nResults\nStructural Steel\n0.00382 in\n"
    ).encode("utf-8")
    r = client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": ("report.txt", report, "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "score" in body and "checks" in body and body["checks"]
    assert body["llm_review"]["available"] is False


def test_quiz_grading_unaffected(client, seeded):
    register_student(client, seeded, "stu_quiz", "pw-eight-chars")
    quiz = client.get("/api/quizzes/quiz_tut1_3d_bar").json()
    answers = [0] * len(quiz["questions"])
    r = client.post("/api/quizzes/quiz_tut1_3d_bar/submissions", json={"answers": answers})
    assert r.status_code == 201 and "score" in r.json()


def test_ai_can_be_switched_back_on(tmp_path):
    """Same build, flag on -> Compass is mounted again."""
    s = Settings(
        data_dir=tmp_path / "on_data", enable_ai=True,
        instructor_username="prof9", instructor_password="prof9-pass-123",
    )
    with TestClient(create_app(s)) as c:
        # 401 (not authenticated), not 404 — the route exists again.
        assert c.get("/api/chatbot/consent").status_code == 401

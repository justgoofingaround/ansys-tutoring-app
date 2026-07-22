"""Instructor report-checking guidelines: settings roundtrip, student
visibility, and threading into the LLM review prompt (no real Ollama)."""

import sys
import types

from server.services import report_verify

from .conftest import login, register_student

GUIDELINES = "Mention mesh convergence and include a deformation contour plot."


def _set_guidelines(client, text):
    return client.post(
        "/api/instructor/tutorials/tut1_3d_bar/settings",
        json={"report_guidelines": text},
    )


def test_settings_roundtrip(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = _set_guidelines(client, GUIDELINES)
    assert r.status_code == 200
    assert r.json()["report_guidelines"] == GUIDELINES

    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    assert lib["tut1_3d_bar"]["report_guidelines"] == GUIDELINES
    # is_mandatory untouched by a guidelines-only update
    assert lib["tut1_3d_bar"]["is_mandatory"] is True

    # empty / whitespace clears to null
    assert _set_guidelines(client, "   ").json()["report_guidelines"] is None
    # over-cap rejected
    assert _set_guidelines(client, "x" * 4001).status_code == 422
    # wrong type rejected
    assert _set_guidelines(client, 123).status_code == 422


def test_student_sees_guidelines(client, seeded):
    login(client, "prof", "prof-pass-123")
    _set_guidelines(client, GUIDELINES)
    client.post("/api/auth/logout", json={})

    register_student(client, seeded)
    detail = client.get("/api/student/tutorials/tut1_3d_bar").json()
    assert detail["report_guidelines"] == GUIDELINES

    client.post("/api/auth/logout", json={})
    login(client, "prof", "prof-pass-123")
    _set_guidelines(client, "")
    client.post("/api/auth/logout", json={})
    login(client, "anna", "hunter2-long")
    assert client.get("/api/student/tutorials/tut1_3d_bar").json()["report_guidelines"] is None


def test_validate_report_forwards_guidelines(tmp_path, monkeypatch):
    """validate_report threads guidelines into the LLM seam and the result
    keys stay intact; deterministic checks don't depend on guidelines."""
    report = tmp_path / "report.txt"
    report.write_text("Static Structural\nSolution\nResults\nStructural Steel\n0.00382 in\n")
    tutorial = {"report_checks": {"required_sections": ["Static Structural"]}}

    seen = {}

    def recorder(text, rubric, summary, guidelines=None):
        seen["guidelines"] = guidelines
        return {"available": True, "model": "fake", "overall": "ok",
                "strengths": [], "caveats": [], "suggestions": [], "confidence": "high"}

    monkeypatch.setattr(report_verify, "_review_report_with_llm", recorder)
    result = report_verify.validate_report(report, tutorial, use_llm=True, guidelines=GUIDELINES)
    assert seen["guidelines"] == GUIDELINES
    assert result["ok"] is True and result["llm_review"]["available"] is True

    # positional two-arg call (the desktop guide's signature) still works
    result = report_verify.validate_report(report, tutorial)
    assert seen["guidelines"] is None
    assert set(result) >= {"ok", "score", "total", "checks", "feedback", "llm_review"}


def test_prompt_contains_delimited_guidelines(monkeypatch):
    """The actual prompt sent to ollama carries the delimited block when
    guidelines are set, and no trace of it when they aren't."""
    captured = {}

    def fake_chat(model, messages, options=None, format=None):
        captured["prompt"] = messages[-1]["content"]
        return {"message": {"content":
                '{"overall": "ok", "strengths": [], "caveats": [], '
                '"suggestions": [], "confidence": "low"}'}}

    fake_ollama = types.SimpleNamespace(chat=fake_chat)
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)

    summary = {"ok": True, "score": 1, "total": 1, "checks": []}
    review = report_verify._review_report_with_llm(
        "Some report text", {}, summary, guidelines=GUIDELINES)
    assert review["available"] is True
    assert "BEGIN INSTRUCTOR GUIDELINES" in captured["prompt"]
    assert GUIDELINES in captured["prompt"]

    report_verify._review_report_with_llm("Some report text", {}, summary, guidelines=None)
    assert "INSTRUCTOR GUIDELINES" not in captured["prompt"]

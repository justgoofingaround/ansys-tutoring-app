"""PDF -> tutorial conversion: deterministic assembly, and the endpoint
with a scripted fake ollama (no real LLM)."""

import io
import json
import re
import sys
import types

import fitz
import pytest

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.services import pdf_tutorial
from tools.validate_tutorial import validate

from .conftest import login, register_student

STEP_ID_RE = re.compile(r"^[a-z]{2}_[0-9]{2}_[a-z0-9_]+$")

METADATA = {"title": "Thermal Analysis of a Bracket",
            "problem": "Find the steady-state temperature field of a steel bracket."}
CHUNK = {
    "section_title": "Set up the model",
    "steps": [
        {"app": "workbench", "title": "Open Workbench",
         "description": "Launch Ansys Workbench from the Start menu.", "hints": ["Use the lab launcher."]},
        {"app": "Mechanical ", "title": "Assign Steel",
         "description": "Set the bracket material to Structural Steel.", "hints": []},
        {"app": "not-an-app", "title": "Generate the mesh",
         "description": "Right-click Mesh and choose Generate Mesh.",
         "hints": ["Default sizing is fine.", "Wait for the green check.", "third hint dropped"]},
        {"app": "mechanical", "title": "", "description": "no title -> dropped"},
    ],
}


# ── unit: assembly ───────────────────────────────────────────────────────


def test_assembly_step_ids_and_coercion():
    data = pdf_tutorial.assemble_tutorial(METADATA, [CHUNK], set(), "brk.pdf", "fake")
    steps = data["sections"][0]["steps"]
    assert len(steps) == 3  # empty-title step dropped
    assert [s["step_id"] for s in steps] == [
        "wb_01_open_workbench", "me_01_assign_steel", "me_02_generate_the_mesh"]
    assert all(STEP_ID_RE.match(s["step_id"]) for s in steps)
    assert steps[1]["app"] == "mechanical"  # " Mechanical " coerced
    assert steps[2]["app"] == "mechanical"  # unknown app coerced
    assert steps[2]["hints"] == ["Default sizing is fine.", "Wait for the green check."]
    assert all(s["highlight"] == "none" for s in steps)
    assert all(s["verify"]["type"] == "manual" and s["verify"]["prompt"] for s in steps)
    assert data["apps"] == ["workbench", "mechanical"]
    assert data["tutorial_id"] == "thermal_analysis_of_a_bracket"
    assert "generated from PDF 'brk.pdf'" in data["_notes"]["source"]


def test_assembly_validates_clean(tmp_path):
    """The load-bearing guarantee: assembled output has ZERO validator errors."""
    data = pdf_tutorial.assemble_tutorial(METADATA, [CHUNK, CHUNK], set(), "x.pdf", "m")
    path = tmp_path / "gen.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    findings = validate(path)
    assert findings.errors == [], findings.items


def test_tutorial_id_collision_suffix():
    existing = {"thermal_analysis_of_a_bracket", "thermal_analysis_of_a_bracket_2"}
    data = pdf_tutorial.assemble_tutorial(METADATA, [CHUNK], existing, "x.pdf", "m")
    assert data["tutorial_id"] == "thermal_analysis_of_a_bracket_3"


# ── endpoint ─────────────────────────────────────────────────────────────


def _tiny_pdf(texts: list[str]) -> bytes:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    return doc.tobytes()


class FakeOllama(types.SimpleNamespace):
    """Scripted format=json responses, queue-ordered."""

    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []
        super().__init__(chat=self._chat)

    def _chat(self, model, messages, format=None, options=None):
        self.calls.append(messages[-1]["content"])
        payload = self.queue.pop(0) if self.queue else "{}"
        return {"message": {"content": payload}}


# Override conftest's settings so app/client/seeded in THIS module share one
# LLM-enabled instance (the conversion gate checks enable_llm first).
@pytest.fixture()
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "server_data", enable_llm=True)


@pytest.fixture()
def llm_client(client):
    return client


def _convert(client, pdf_bytes, name="tutorial.pdf"):
    return client.post(
        "/api/instructor/tutorials/from-pdf",
        files={"file": (name, io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"X-Requested-With": "fetch"},
    )


def test_endpoint_happy_path(llm_client, seeded, monkeypatch):
    fake = FakeOllama([json.dumps(METADATA), json.dumps(CHUNK)])
    monkeypatch.setitem(sys.modules, "ollama", fake)
    login(llm_client, "prof", "prof-pass-123")
    r = _convert(llm_client, _tiny_pdf(["Step 1: open workbench. Step 2: mesh."]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tutorial_id"] == "thermal_analysis_of_a_bracket"
    assert body["generated"]["model"] and body["generated"]["skipped_chunks"] == 0

    lib = {t["tutorial_id"]: t for t in llm_client.get("/api/instructor/tutorials").json()}
    assert lib["thermal_analysis_of_a_bracket"]["published_version"] is None  # draft

    # invisible to students until published
    llm_client.post("/api/auth/logout", json={})
    register_student(llm_client, seeded)
    ids = {t["tutorial_id"] for t in llm_client.get("/api/tutorials").json()}
    assert "thermal_analysis_of_a_bracket" not in ids


def test_llm_disabled_503(tmp_path):
    off = Settings(
        data_dir=tmp_path / "off_data", enable_llm=False,
        instructor_username="prof2", instructor_password="prof2-pass-123",
    )
    with TestClient(create_app(off)) as c:
        login(c, "prof2", "prof2-pass-123")
        r = _convert(c, _tiny_pdf(["text"]))
        assert r.status_code == 503


def test_not_a_pdf_422(llm_client, seeded):
    login(llm_client, "prof", "prof-pass-123")
    r = _convert(llm_client, b"this is not a pdf")
    assert r.status_code == 422
    assert "not_a_pdf" in r.json()["detail"]


def test_garbage_chunk_skipped(llm_client, seeded, monkeypatch):
    """One chunk returns garbage twice -> skipped, conversion still succeeds."""
    fake = FakeOllama([
        json.dumps(METADATA),
        json.dumps(CHUNK),      # chunk 1 ok
        "not json", "also bad"  # chunk 2 fails twice -> skipped
    ])
    monkeypatch.setitem(sys.modules, "ollama", fake)
    login(llm_client, "prof", "prof-pass-123")
    pdf = _tiny_pdf(["page1", "page2", "page3", "page4"])  # 4 pages -> 2 chunks
    r = _convert(llm_client, pdf)
    assert r.status_code == 201, r.text
    assert r.json()["generated"]["skipped_chunks"] == 1


def test_all_garbage_502(llm_client, seeded, monkeypatch):
    fake = FakeOllama(["bad"] * 10)
    monkeypatch.setitem(sys.modules, "ollama", fake)
    login(llm_client, "prof", "prof-pass-123")
    r = _convert(llm_client, _tiny_pdf(["some text"]))
    assert r.status_code == 502


def test_student_cannot_convert(llm_client, seeded):
    register_student(llm_client, seeded)
    r = _convert(llm_client, _tiny_pdf(["x"]))
    assert r.status_code == 403

"""Compass chatbot: consent gate, SSE frame sequence, non-stream mode,
FERPA-safe query logging. All through FakeChatbotEngine — no Ollama."""

import json

import pytest

from server import db as dbmod
from server.app import create_app
from server.config import Settings
from server.services.chatbot_service import FakeChatbotEngine

from .conftest import login, register_student
from fastapi.testclient import TestClient


@pytest.fixture()
def engine():
    return FakeChatbotEngine()


@pytest.fixture()
def settings(tmp_path, engine):
    return Settings(data_dir=tmp_path / "server_data", enable_llm=False, chatbot_engine=engine)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _consent(client):
    r = client.post("/api/chatbot/consent", json={"granted": True})
    assert r.status_code == 200 and r.json()["granted"] is True


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event:
            events.append((event, data))
    return events


def test_query_requires_consent(client, seeded):
    register_student(client, seeded)
    r = client.post("/api/chatbot/query", json={"question": "How do I mesh?"})
    assert r.status_code == 403
    assert r.json()["detail"] == "consent_required"


def test_consent_roundtrip_and_me_flag(client, seeded):
    register_student(client, seeded)
    assert client.get("/api/chatbot/consent").json()["granted"] is False
    _consent(client)
    assert client.get("/api/chatbot/consent").json()["granted"] is True
    assert client.get("/api/auth/me").json()["chatbot_consent"] is True
    client.post("/api/chatbot/consent", json={"granted": False})
    assert client.get("/api/chatbot/consent").json()["granted"] is False


def test_sse_frame_sequence(client, seeded, engine):
    register_student(client, seeded)
    _consent(client)
    r = client.post(
        "/api/chatbot/query",
        json={"question": "Why did my mesh fail?", "tutorial_id": "tut1_3d_bar"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and events[0][1]["model"] == "fake-model"
    assert kinds[-2:] == ["sources", "done"]
    token_text = "".join(d["t"] for k, d in events if k == "token")
    assert token_text == "To fix a failed mesh, check the geometry. [1]"
    sources = next(d for k, d in events if k == "sources")["sources"]
    assert sources == ["Meshing Guide - Section 2.1"]
    # Tutorial context was threaded into the engine
    assert "Tutorial 1" in engine.calls[0]["tutorial_context"]


def test_non_stream_mode(client, seeded):
    register_student(client, seeded)
    _consent(client)
    r = client.post("/api/chatbot/query", json={"question": "hello", "stream": False})
    body = r.json()
    assert body["answer"].endswith("[1]")
    assert body["sources"] and body["model"] == "fake-model"


def test_query_logged_with_opaque_token(client, seeded, settings):
    me = register_student(client, seeded)
    _consent(client)
    client.post("/api/chatbot/query", json={"question": "What is a fixed support?"})
    conn = dbmod.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM chatbot_queries").fetchone()
        assert row["session_token"] == me["opaque_token"]
        assert row["question"] == "What is a fixed support?"
        assert "mesh" in row["answer"]  # fake engine's canned answer, fully logged
        assert json.loads(row["sources"]) == ["Meshing Guide - Section 2.1"]
    finally:
        conn.close()


def test_error_event_when_engine_fails(client, seeded, engine):
    def boom(question, tutorial_context, on_token):
        raise RuntimeError("ollama down")

    engine.generate = boom
    register_student(client, seeded)
    _consent(client)
    r = client.post("/api/chatbot/query", json={"question": "hi"})
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert "ollama down" in events[-1][1]["detail"]


def test_instructor_cannot_query(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post("/api/chatbot/query", json={"question": "hi"})
    assert r.status_code == 403


# ── CloudApiEngine (cloud deployments: CHATBOT_API_KEY set, no Ollama) ──

def test_get_engine_prefers_cloud_when_api_key_set(tmp_path):
    from server.services import chatbot_service

    s = Settings(
        data_dir=tmp_path / "server_data",
        chatbot_api_key="test-key",
        chatbot_api_base="https://api.example/v1",
        chatbot_model="test-model",
    )
    chatbot_service._default_engine = None
    try:
        eng = chatbot_service.get_engine(s)
        assert isinstance(eng, chatbot_service.CloudApiEngine)
        assert eng.model == "test-model"
        assert eng.api_base == "https://api.example/v1"
    finally:
        chatbot_service._default_engine = None


def test_cloud_engine_streams_openai_sse():
    import httpx

    from server.services.chatbot_service import CloudApiEngine

    sse = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        ": keep-alive\n\n"
        "data: [DONE]\n\n"
    )

    def handler(request):
        assert request.url == "https://api.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model" and body["stream"] is True
        assert "Tutorial context: Tutorial 1" in body["messages"][1]["content"]
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    engine = CloudApiEngine(
        "https://api.example/v1", "test-key", "test-model",
        transport=httpx.MockTransport(handler),
    )
    tokens = []
    answer, sources = engine.generate("hi", "Tutorial 1", tokens.append)
    assert answer == "Hello world"
    assert tokens == ["Hello ", "world"]
    assert sources == []  # no retrieval index in cloud mode


def test_cloud_engine_raises_on_api_error():
    import httpx

    from server.services.chatbot_service import CloudApiEngine

    engine = CloudApiEngine(
        "https://api.example/v1", "bad-key", "test-model",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(401, json={"error": "invalid key"})
        ),
    )
    with pytest.raises(RuntimeError, match="401"):
        engine.generate("hi", None, lambda _t: None)

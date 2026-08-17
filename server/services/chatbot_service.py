"""Compass chatbot engine seam.

The router talks to a ChatbotEngine protocol; the real implementation
bridges to chatbot_spike/ (retrieve + stream_answer over local Ollama, the
same in-process bridge guide_tut1.py uses). Tests inject FakeChatbotEngine
through Settings.chatbot_engine so no Ollama/ChromaDB/embedding model is
needed to exercise the API.

Cloud deployments (no Ollama, no retrieval index in the image) set
CHATBOT_API_KEY to route generation through CloudApiEngine instead — an
OpenAI-compatible chat-completions API with no retrieval, demo-grade only.

All real Ollama generation is serialized behind one lock: the instructor
desktop has ONE GPU and the embedding model + Ollama are not safely
concurrent at useful speed; a second student's query simply queues for a
few seconds. The cloud API is concurrency-safe and takes no lock.
"""

import json
import threading
from typing import Callable, Protocol


class ChatbotEngine(Protocol):
    model: str

    def generate(
        self,
        question: str,
        tutorial_context: str | None,
        on_token: Callable[[str], None],
    ) -> tuple[str, list[str]]:
        """Stream an answer via on_token; return (full_answer, sources)."""
        ...


class OllamaEngine:
    """Real engine: chatbot_spike's retrieve + stream_answer pipeline.
    Imports lazily so a broken/absent chatbot install breaks only the
    chatbot endpoints (they surface a clean SSE error event), never boot."""

    def __init__(self):
        self._lock = threading.Lock()
        self.model = "unknown"
        try:
            from config import OLLAMA_MODEL  # chatbot_spike/config.py (sys.path bridge)

            self.model = OLLAMA_MODEL
        except Exception:
            pass

    def generate(self, question, tutorial_context, on_token):
        with self._lock:
            try:
                from retrieve import retrieve
                from generate import stream_answer
            except ModuleNotFoundError as exc:
                if exc.name == "retrieve":
                    raise RuntimeError(
                        "Chatbot retrieval assets are not available in this environment. "
                        "Install the chatbot_spike dependency set or run the app from the repo root with the bundled chatbot_spike package on PYTHONPATH."
                    ) from exc
                raise

            chunks = retrieve(question)
            return stream_answer(
                question, chunks, tutorial_context=tutorial_context, on_token=on_token
            )


CLOUD_SYSTEM_PROMPT = """You are Compass, an assistant embedded in a tutoring tool for NYU's \
ME-UY 4214 Finite Element Analysis course, helping students use Ansys Workbench, Discovery, \
and Mechanical. If asked your name, say you're Compass.

Rules:
1. Answer from your general Ansys knowledge. This deployment has no documentation \
index, so do NOT emit bracketed citations like [1] — plain prose only.
2. BE BRIEF — a student is mid-tutorial waiting for an answer. Default to 2-4 short \
sentences or a short list of 2-3 steps. Only go longer if the question explicitly asks \
for a full walkthrough or a comparison of multiple methods.
3. If tutorial context is provided, tailor the answer to that step rather than giving \
a fully generic answer — don't re-explain things the student has clearly already done.
4. If you aren't sure, say so plainly instead of guessing."""

# Brevity is enforced by the prompt; the token cap is a backstop. It is
# deliberately larger than the visible answer needs to be: reasoning models
# (e.g. Groq's gpt-oss-*) spend completion tokens on internal reasoning
# first, and a tight cap yields empty answers.
CLOUD_MAX_RESPONSE_TOKENS = 1024


class CloudApiEngine:
    """OpenAI-compatible chat-completions bridge (Groq, OpenRouter, anything
    speaking POST /chat/completions with SSE streaming) for cloud/demo
    deployments where neither Ollama nor the chatbot_spike index exists.

    NO RETRIEVAL: answers come from the model's general knowledge, so the
    sources list is always empty and the prompt forbids inline [n] markers
    (nothing to cite). The NYU pilot never uses this engine — student data
    stays off cloud LLMs by leaving CHATBOT_API_KEY unset there."""

    def __init__(self, api_base: str, api_key: str, model: str, transport=None):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._transport = transport  # test seam: httpx.MockTransport

    def generate(self, question, tutorial_context, on_token):
        import httpx  # lazy, mirrors OllamaEngine: a missing dep breaks only chatbot endpoints

        parts = []
        if tutorial_context:
            parts.append(f"Tutorial context: {tutorial_context}")
        parts.append(f"Student question: {question}")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": CLOUD_SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
            "max_tokens": CLOUD_MAX_RESPONSE_TOKENS,
            "stream": True,
        }
        pieces: list[str] = []
        with httpx.Client(
            transport=self._transport, timeout=httpx.Timeout(60.0, connect=10.0)
        ) as client:
            with client.stream(
                "POST",
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="replace")[:300]
                    raise RuntimeError(f"chatbot API returned {resp.status_code}: {body}")
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue  # comments / keep-alives
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    choices = json.loads(data).get("choices") or []
                    if not choices:
                        continue
                    piece = (choices[0].get("delta") or {}).get("content") or ""
                    if piece:
                        pieces.append(piece)
                        on_token(piece)
        return "".join(pieces), []


class FakeChatbotEngine:
    """Deterministic engine for tests/dev: streams the question back in a
    few pieces, cites a fixed source."""

    model = "fake-model"

    def __init__(self, pieces: list[str] | None = None, sources: list[str] | None = None):
        self.pieces = pieces or ["To fix a ", "failed mesh, ", "check the geometry. [1]"]
        self.sources = sources if sources is not None else ["Meshing Guide - Section 2.1"]
        self.calls: list[dict] = []

    def generate(self, question, tutorial_context, on_token):
        self.calls.append({"question": question, "tutorial_context": tutorial_context})
        for p in self.pieces:
            on_token(p)
        return "".join(self.pieces), list(self.sources)


_default_engine: ChatbotEngine | None = None
_default_engine_lock = threading.Lock()


def get_engine(settings) -> ChatbotEngine:
    """Settings.chatbot_engine (test seam), else a process-wide engine:
    CloudApiEngine when an API key is configured, local OllamaEngine otherwise."""
    if settings.chatbot_engine is not None:
        return settings.chatbot_engine
    global _default_engine
    with _default_engine_lock:
        if _default_engine is None:
            if settings.chatbot_api_key:
                _default_engine = CloudApiEngine(
                    settings.chatbot_api_base, settings.chatbot_api_key, settings.chatbot_model
                )
            else:
                _default_engine = OllamaEngine()
        return _default_engine

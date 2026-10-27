"""Compass chatbot engine seam.

The router talks to a ChatbotEngine protocol; the real implementation
bridges to compass/ (retrieve + stream_answer over local Ollama, the
same in-process bridge guide_tut1.py uses). Tests inject FakeChatbotEngine
through Settings.chatbot_engine so no Ollama/ChromaDB/embedding model is
needed to exercise the API.

Ollama is the only generation backend there is. A deployment without it has
no chatbot, which is the honest outcome: the alternative was a cloud API
key, and that is a path student questions could leave NYU hardware by.

All generation is serialized behind one lock: the instructor desktop has ONE
GPU and the embedding model + Ollama are not safely concurrent at useful
speed; a second student's query simply queues for a few seconds.
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
    """Real engine: compass's retrieve + stream_answer pipeline.
    Imports lazily so a broken/absent chatbot install breaks only the
    chatbot endpoints (they surface a clean SSE error event), never boot."""

    def __init__(self):
        self._lock = threading.Lock()
        self.model = "unknown"
        try:
            from config import OLLAMA_MODEL  # compass/config.py (sys.path bridge)

            self.model = OLLAMA_MODEL
        except Exception:
            pass

    def generate(self, question, tutorial_context, on_token):
        with self._lock:
            try:
                from retrieve import retrieve
                from generate import stream_answer
                from config import CHROMA_DIR
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Compass document search is not installed in this environment "
                    f"(missing module: {exc.name}). Build the image with WITH_COMPASS=1, "
                    "or install compass/requirements.txt for a local run."
                ) from exc
            # Check before retrieve(): chromadb would otherwise create an empty
            # index in the (mounted) folder, and every question would get
            # "couldn't find anything" instead of a clear error.
            if not (CHROMA_DIR / "chroma.sqlite3").exists():
                raise RuntimeError(
                    f"Compass document index is not installed: {CHROMA_DIR} has no "
                    "chroma.sqlite3. Copy compass/data/ from the machine that built it."
                )

            chunks = retrieve(question)
            return stream_answer(
                question, chunks, tutorial_context=tutorial_context, on_token=on_token
            )


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
    """Settings.chatbot_engine (test seam), else one process-wide OllamaEngine."""
    if settings.chatbot_engine is not None:
        return settings.chatbot_engine
    global _default_engine
    with _default_engine_lock:
        if _default_engine is None:
            _default_engine = OllamaEngine()
        return _default_engine

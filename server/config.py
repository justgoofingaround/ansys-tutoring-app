"""Server settings + repo path pinning.

REPO_ROOT goes on sys.path so `tools.validate_tutorial` and the promoted
services resolve, and chatbot_spike/ (bare intra-package imports) gets the
same sys.path bridge spikes/guide_tut1.py uses.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CHATBOT_DIR = REPO_ROOT / "chatbot_spike"
if CHATBOT_DIR.exists() and str(CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(CHATBOT_DIR))

def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines, # comments; real environment
    variables always win). Secrets like CHATBOT_API_KEY live in the
    gitignored repo-root .env so they never enter git; deployments set real
    env vars instead. Must run before Settings is defined — its field
    defaults read os.environ at class-creation time."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(REPO_ROOT / ".env")

SESSION_COOKIE = "session"


@dataclass
class Settings:
    # DATA_DIR env lets deployments point at a mounted volume; tests and
    # local runs keep the repo-relative default (kwarg always wins).
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("DATA_DIR", REPO_ROOT / "server_data"))
    )
    session_ttl_days: float = 14.0
    enable_llm: bool = os.environ.get("ENABLE_LLM", "1") == "1"
    # Cloud/demo deployments seed the whole mock_server/data catalog on first
    # boot (ephemeral disks re-seed on every restart); local/dev/tests seed
    # only tut1 as before.
    seed_all_tutorials: bool = os.environ.get("SEED_ALL_TUTORIALS", "0") == "1"
    faq_threshold: float = 0.30
    faq_min_cohort: int = 5
    max_report_bytes: int = 20 * 1024 * 1024
    instructor_username: str | None = os.environ.get("INSTRUCTOR_USERNAME")
    instructor_password: str | None = os.environ.get("INSTRUCTOR_PASSWORD")
    # COOKIE_SECURE=1 for HTTPS deployments (nginx + TLS); off by default so
    # the plain-HTTP LAN/dev flow keeps working.
    cookie_secure: bool = os.environ.get("COOKIE_SECURE", "0") == "1"
    # Test seam: routers pull the chatbot engine from app.state; tests inject a fake.
    chatbot_engine: object | None = None
    # Cloud chatbot: when CHATBOT_API_KEY is set, Compass answers through an
    # OpenAI-compatible chat-completions API (Groq, OpenRouter, ...) instead
    # of local Ollama + the chatbot_spike retrieval index. Team-testing/demo
    # deployments only — the NYU pilot keeps the FERPA invariant (no cloud
    # LLM touches student data) by leaving this unset.
    chatbot_api_key: str | None = os.environ.get("CHATBOT_API_KEY") or None
    chatbot_api_base: str = os.environ.get("CHATBOT_API_BASE", "https://api.groq.com/openai/v1")
    chatbot_model: str = os.environ.get("CHATBOT_MODEL", "llama-3.1-8b-instant")
    # Derived paths
    db_path: Path = field(init=False)

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.db_path = self.data_dir / "app.db"

    @property
    def tutorials_dir(self) -> Path:
        return self.data_dir / "tutorials"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "uploads" / "reports"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.tutorials_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

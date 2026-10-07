"""Server settings + repo path pinning.

REPO_ROOT goes on sys.path so `tools.validate_tutorial` and the promoted
services resolve, and compass/ (bare intra-package imports) gets the
same sys.path bridge student_app/guide_tut1.py uses.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CHATBOT_DIR = REPO_ROOT / "compass"
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
    # Master AI switch. OFF unless ENABLE_AI=1 is set explicitly: a deployment
    # that forgets the variable runs with no AI at all, which is the safe
    # failure direction while the NYU security review is open. When off,
    # __post_init__ forces every other AI seam off too (including a stray
    # CHATBOT_API_KEY), so no single missed env var can switch generation back on.
    enable_ai: bool = os.environ.get("ENABLE_AI", "0") == "1"
    enable_llm: bool = os.environ.get("ENABLE_LLM", "1") == "1"
    # Cloud/demo deployments seed the whole content/data catalog on first
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
    # --- Registration confirmation mail (see services/mailer.py) ---
    # SMTP_HOST unset -> links are logged, not sent; the instructor can still
    # admit a student manually from the roster.
    smtp_host: str | None = os.environ.get("SMTP_HOST") or None
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str | None = os.environ.get("SMTP_USER") or None
    smtp_password: str | None = os.environ.get("SMTP_PASSWORD") or None
    smtp_from: str | None = os.environ.get("SMTP_FROM") or None
    # Base URL the confirmation link points at — must match how students reach
    # the app (https://meuy4214.poly.edu on the pilot host).
    app_base_url: str = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000")
    verification_ttl_hours: float = 48.0
    # Shorter than a confirmation link: a reset link is a live credential.
    reset_ttl_hours: float = 2.0
    resend_cooldown_seconds: float = 60.0
    mailer: object | None = None  # test seam, mirrors chatbot_engine
    # Cloud chatbot: when CHATBOT_API_KEY is set, Compass answers through an
    # OpenAI-compatible chat-completions API (Groq, OpenRouter, ...) instead
    # of local Ollama + the compass retrieval index. Team-testing/demo
    # deployments only — the NYU pilot keeps the FERPA invariant (no cloud
    # LLM touches student data) by leaving this unset.
    chatbot_api_key: str | None = os.environ.get("CHATBOT_API_KEY") or None
    chatbot_api_base: str = os.environ.get("CHATBOT_API_BASE", "https://api.groq.com/openai/v1")
    chatbot_model: str = os.environ.get("CHATBOT_MODEL", "openai/gpt-oss-20b")
    # Derived paths
    db_path: Path = field(init=False)

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.db_path = self.data_dir / "app.db"
        if not self.enable_ai:
            # Single authority: the existing per-feature gates (report review,
            # FAQ drafting, PDF->tutorial) all read enable_llm, and both the
            # Compass cloud engine and the PDF cloud fallback read
            # chatbot_api_key. Clearing them here disables every generation
            # path without scattering `enable_ai` checks through the services.
            self.enable_llm = False
            self.chatbot_api_key = None

    @property
    def tutorials_dir(self) -> Path:
        return self.data_dir / "tutorials"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "uploads" / "reports"

    @property
    def step_images_dir(self) -> Path:
        """Step reference screenshots uploaded through the tutorial editor.

        Deliberately under DATA_DIR, not the repo: content/data/images is
        baked into the Docker image, so anything written there is lost on the
        next redeploy. DATA_DIR is the bind-mounted volume."""
        return self.data_dir / "uploads" / "step_images"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.tutorials_dir, self.reports_dir,
                  self.step_images_dir):
            d.mkdir(parents=True, exist_ok=True)

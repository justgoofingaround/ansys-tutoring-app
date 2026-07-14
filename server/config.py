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

SESSION_COOKIE = "session"


@dataclass
class Settings:
    data_dir: Path = REPO_ROOT / "server_data"
    session_ttl_days: float = 14.0
    enable_llm: bool = os.environ.get("ENABLE_LLM", "1") == "1"
    faq_threshold: float = 0.30
    faq_min_cohort: int = 5
    max_report_bytes: int = 20 * 1024 * 1024
    instructor_username: str | None = os.environ.get("INSTRUCTOR_USERNAME")
    instructor_password: str | None = os.environ.get("INSTRUCTOR_PASSWORD")
    # Test seam: routers pull the chatbot engine from app.state; tests inject a fake.
    chatbot_engine: object | None = None
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

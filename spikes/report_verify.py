"""Shim: the report validator was promoted to server/services/report_verify.py
(it is shipped server code now, and spikes/ is not shipped). This re-export
keeps `import report_verify` in guide_tut1.py working unchanged."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.services.report_verify import *  # noqa: F401,F403
from server.services.report_verify import validate_report  # noqa: F401

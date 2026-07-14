"""Target of the ansysguide:// URL protocol.

The browser invokes this as:  pythonw.exe guide_launcher.py "ansysguide://<tutorial_id>"
It spawns the desktop guide (spikes/guide_tut1.py) for that tutorial and
exits. Runs under pythonw (no console), so everything is logged to
server_data/guide_launcher.log for debugging.

The special URL "ansysguide://close" doesn't launch anything — it drops a
stop-sentinel file that a running guide notices on its next tick (<1 s) and
shuts down cleanly. This is how the web app's "Close guide" button works.

Register the protocol once per PC with:
    .venv\\Scripts\\python tools\\register_guide_protocol.py
"""

import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "spikes" / "guide_tut1.py"
LOG = REPO_ROOT / "server_data" / "guide_launcher.log"
# Must match STOP_FILE in spikes/guide_tut1.py — the guide polls for it.
STOP_FILE = REPO_ROOT / "server_data" / "guide_stop"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


def tutorial_id_from_url(url: str) -> str:
    """ansysguide://tut1_3d_bar/  ->  tut1_3d_bar
    Browsers may append a trailing slash and percent-encode."""
    rest = url.split("://", 1)[1] if "://" in url else url
    return urllib.parse.unquote(rest).strip("/ ")


def main(argv: list[str]) -> int:
    url = argv[0] if argv else ""
    tutorial_id = tutorial_id_from_url(url)
    if not tutorial_id:
        log(f"rejected: no tutorial id in {url!r}")
        return 1
    if tutorial_id == "close":
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        log("close requested: stop file written")
        return 0
    # Same interpreter flavour we were launched with (the venv's pythonw).
    cmd = [sys.executable, str(GUIDE), tutorial_id]
    log(f"launching: {cmd}")
    try:
        subprocess.Popen(cmd, cwd=str(REPO_ROOT))
    except OSError as exc:
        log(f"launch FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

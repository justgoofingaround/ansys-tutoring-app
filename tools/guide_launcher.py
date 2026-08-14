"""Target of the ansysguide:// URL protocol.

The browser invokes this as:
    pythonw.exe guide_launcher.py "ansysguide://<tutorial_id>?server=<hub-origin>"
When the optional server param is present, the launcher first syncs the
published tutorial JSON (and step reference images) from the hub, so the
guide always runs the latest published version without a manual download.
It then spawns the desktop guide (spikes/guide_tut1.py) for that tutorial
and exits. Runs under pythonw (no console), so everything is logged to
server_data/guide_launcher.log for debugging.

The special URL "ansysguide://close" doesn't launch anything — it drops a
stop-sentinel file that a running guide notices on its next tick (<1 s) and
shuts down cleanly. This is how the web app's "Close guide" button works.

Register the protocol once per PC with:
    .venv\\Scripts\\python tools\\register_guide_protocol.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "spikes" / "guide_tut1.py"
TUTORIALS_DIR = REPO_ROOT / "mock_server" / "data"
IMAGES_PREFIX = "mock_server/data/images/"
LOG = REPO_ROOT / "server_data" / "guide_launcher.log"
# Must match STOP_FILE in spikes/guide_tut1.py — the guide polls for it.
STOP_FILE = REPO_ROOT / "server_data" / "guide_stop"

# Tutorial ids are slugs; anything else (path separators, dots) is rejected
# before it can reach the filesystem or the hub URL.
TUTORIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$", re.IGNORECASE)
FETCH_TIMEOUT_S = 10


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


def parse_url(url: str) -> tuple[str, str]:
    """ansysguide://tut1_3d_bar/?server=http%3A%2F%2Fhub%3A8000
    -> ("tut1_3d_bar", "http://hub:8000")
    Browsers may append a trailing slash and percent-encode. The server
    param is optional (older links carry only the id)."""
    rest = url.split("://", 1)[1] if "://" in url else url
    rest, _, query = rest.partition("?")
    tutorial_id = urllib.parse.unquote(rest).strip("/ ")
    server = urllib.parse.parse_qs(query).get("server", [""])[0].strip().rstrip("/")
    return tutorial_id, server


def refresh_from_hub(server: str, tutorial_id: str) -> None:
    """Best-effort content sync: pull the published tutorial JSON (and any
    step reference images) from the hub so the guide always runs the latest
    published version. Raises on failure; the caller logs and falls back to
    whatever is already on disk."""
    url = f"{server}/api/guide/tutorials/{urllib.parse.quote(tutorial_id)}"
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    dest = TUTORIALS_DIR / f"{tutorial_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"synced tutorial JSON v{data.get('version')} from {server}")

    images_root = (REPO_ROOT / IMAGES_PREFIX).resolve()
    for section in data.get("sections", []):
        for step in section.get("steps", []):
            img = step.get("source_image")
            rel = img.replace("\\", "/") if isinstance(img, str) else ""
            if not rel.startswith(IMAGES_PREFIX):
                continue
            target = (REPO_ROOT / rel).resolve()
            if images_root not in target.parents:  # traversal guard
                log(f"skipped suspicious image path: {rel}")
                continue
            img_url = f"{server}/tutorial-images/{urllib.parse.quote(rel[len(IMAGES_PREFIX):])}"
            try:
                with urllib.request.urlopen(img_url, timeout=FETCH_TIMEOUT_S) as r:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(r.read())
            except Exception as exc:
                log(f"image sync failed ({rel}): {exc}")


def main(argv: list[str]) -> int:
    url = argv[0] if argv else ""
    tutorial_id, server = parse_url(url)
    if not tutorial_id:
        log(f"rejected: no tutorial id in {url!r}")
        return 1
    if tutorial_id == "close":
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        log("close requested: stop file written")
        return 0
    if not TUTORIAL_ID_RE.match(tutorial_id):
        log(f"rejected: invalid tutorial id {tutorial_id!r}")
        return 1
    if server:
        try:
            refresh_from_hub(server, tutorial_id)
        except Exception as exc:
            log(f"hub sync failed ({exc}); using the local copy if present")
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

"""guide_launcher URL parsing + tutorial-id validation (pure functions;
no protocol registration or subprocess involved)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "guide_launcher", REPO_ROOT / "tools" / "guide_launcher.py"
)
guide_launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guide_launcher)


def test_parse_url_id_only():
    assert guide_launcher.parse_url("ansysguide://tut1_3d_bar") == ("tut1_3d_bar", "")
    # browsers may append a trailing slash
    assert guide_launcher.parse_url("ansysguide://tut1_3d_bar/") == ("tut1_3d_bar", "")
    assert guide_launcher.parse_url("ansysguide://close") == ("close", "")


def test_parse_url_with_server():
    tid, server = guide_launcher.parse_url(
        "ansysguide://tut1_3d_bar/?server=http%3A%2F%2Fhub.local%3A8000"
    )
    assert tid == "tut1_3d_bar"
    assert server == "http://hub.local:8000"
    # trailing slash on the origin is normalized away
    _, server = guide_launcher.parse_url(
        "ansysguide://tut1?server=http%3A%2F%2Fhub%3A8000%2F"
    )
    assert server == "http://hub:8000"


def test_tutorial_id_validation():
    ok = guide_launcher.TUTORIAL_ID_RE.match
    assert ok("tut1_3d_bar")
    assert ok("m01_intro-valve")
    assert not ok("../../evil")
    assert not ok("a/b")
    assert not ok("a.b")
    assert not ok("")

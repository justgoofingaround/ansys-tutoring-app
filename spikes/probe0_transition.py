"""
Probe 0 — Can we detect a child Ansys app window appearing on transition?

THROWAWAY SPIKE CODE. This is the core of the bridge's app-transition handling
(the LAUNCHING state from the eng review): highlight the launch action in
Workbench, then WAIT for the new app's window before resuming in that app.

WHAT IT DOES:
  1. Confirms a Workbench window is present.
  2. Polls for a Discovery (or Mechanical) window to appear for up to TIMEOUT s.
  3. You trigger the launch by hand (double-click the Geometry cell in Workbench)
     while this is running.

PASS if it prints "Workbench up", then after you open the Geometry cell,
"<app> appeared after N.N s" well within the timeout.

NOTE: cold-launching Discovery/Mechanical can take 30-90s — that's exactly why
the plan uses a long, configurable timeout, not "a few seconds".

SETUP:
  pip install pywinauto
  Open Workbench (with a Static Structural system), run this, THEN double-click
  the Geometry cell:   python probe0_transition.py
"""

import sys
import time

try:
    from pywinauto import Desktop
except ImportError:
    sys.exit("pywinauto not installed.  pip install pywinauto")

TIMEOUT = 120.0          # generous: matches the LAUNCHING timeout in the plan
POLL_INTERVAL = 0.5
# Title fragments per app. Adjust to whatever the real windows report.
APP_TITLES = {
    "workbench": "Workbench",
    "discovery": "Discovery",
    "mechanical": "Mechanical",
}
WATCH_FOR = "discovery"  # change to "mechanical" to probe the Model-cell transition


def find_window(title_fragment):
    """Return the first top-level window whose title contains the fragment."""
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text() or ""
        except Exception:
            continue
        if title_fragment.lower() in title.lower():
            return w
    return None


def main():
    if find_window(APP_TITLES["workbench"]) is None:
        sys.exit("FAIL: no Workbench window. Open Ansys Workbench first.")
    print("Workbench up.")
    print(f"Now trigger the transition (double-click the Geometry/Model cell). "
          f"Waiting up to {TIMEOUT:.0f}s for a '{WATCH_FOR}' window...")

    target = APP_TITLES[WATCH_FOR]
    start = time.monotonic()
    while time.monotonic() - start < TIMEOUT:
        win = find_window(target)
        if win is not None:
            elapsed = time.monotonic() - start
            print(f"PASS: {WATCH_FOR} appeared after {elapsed:.1f} s")
            try:
                print("  title:", win.window_text())
                print("  rect: ", win.rectangle())
            except Exception:
                pass
            return
        time.sleep(POLL_INTERVAL)

    sys.exit(f"TIMEOUT: no '{target}' window within {TIMEOUT:.0f}s. "
             f"Did the app open? Is the title different from '{target}'?")


if __name__ == "__main__":
    main()

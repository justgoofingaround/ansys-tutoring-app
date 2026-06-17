"""
Probe 2 — Can UI Automation see Ansys Workbench, and give stable element boxes?

THROWAWAY SPIKE CODE. Not shipped. Goal: answer, for the FIRST app in a tutorial
(Workbench), "can the bridge locate elements?" before we build the real bridge.

PASS if:
  - it connects to the Workbench window and prints its rectangle, AND
  - it prints a name + screen rectangle for at least one Toolbox item
    (e.g. "Static Structural") and one schematic cell (e.g. "Geometry").
WATCH FOR:
  - elements with empty automation_id (we prefer automation_id over name for
    stability across Ansys versions — record which surfaces expose it).
  - the project schematic showing as one opaque element (it may be custom-drawn,
    like the 3D viewports in Discovery/Mechanical — record it).

SETUP:
  pip install pywinauto
  Open Ansys Workbench, create/load a project with a Static Structural system
  (so the Geometry and Model cells exist), then run:  python probe2_uia_workbench.py
"""

import sys

try:
    from pywinauto import Desktop
except ImportError:
    sys.exit("pywinauto not installed.  pip install pywinauto")

TITLE_HINT = "Workbench"          # matched case-insensitively against window title
KEYWORDS = ("Static Structural", "Geometry", "Model", "Toolbox")  # things to find
MAX_DUMP = 60                     # cap the shallow tree dump so we don't flood


def find_workbench():
    """Return the top-level Workbench window, or None."""
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text() or ""
        except Exception:
            continue
        if TITLE_HINT.lower() in title.lower():
            return w
    return None


def describe(ctrl):
    """One-line description of a UIA control: name | automation_id | type | rect."""
    info = ctrl.element_info
    try:
        rect = ctrl.rectangle()
    except Exception:
        rect = "?"
    return (
        f"name={info.name!r:40} "
        f"auto_id={ (info.automation_id or '-')!r:20} "
        f"type={info.control_type:18} "
        f"rect={rect}"
    )


def main():
    wb = find_workbench()
    if wb is None:
        sys.exit(
            "FAIL: no window whose title contains 'Workbench'.\n"
            "Is Ansys Workbench open?  If the title differs, edit TITLE_HINT."
        )

    print("=== Workbench window ===")
    print(describe(wb))
    print()

    # Walk descendants once; pywinauto's descendants() can be slow on a big tree,
    # which is itself a useful signal about UIA cost (see the perf risk in the plan).
    print("=== Scanning descendants for keywords ===")
    hits, shown = 0, 0
    try:
        descendants = wb.descendants()
    except Exception as e:
        sys.exit(f"FAIL: could not enumerate descendants: {e}")

    for ctrl in descendants:
        name = (ctrl.element_info.name or "")
        if any(k.lower() in name.lower() for k in KEYWORDS):
            print("  HIT:", describe(ctrl))
            hits += 1

    print(f"\nKeyword hits: {hits}")
    print(f"Total UIA descendants walked: {len(descendants)} "
          f"(note how long this took — that's the 10 Hz polling concern)\n")

    print("=== Shallow tree sample (first", MAX_DUMP, "controls) ===")
    for ctrl in descendants[:MAX_DUMP]:
        print(" ", describe(ctrl))
        shown += 1

    print()
    if hits:
        print("PASS-ish: UIA can see named Workbench elements with rectangles.")
        print("Record which hits had a non-empty auto_id (preferred for selectors).")
    else:
        print("PARTIAL: connected to Workbench but found none of", KEYWORDS)
        print("Try editing KEYWORDS to match what you actually see in the dump above.")


if __name__ == "__main__":
    main()

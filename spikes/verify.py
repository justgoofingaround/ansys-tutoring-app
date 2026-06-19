"""
Step verification -- separate from the UI/panel script on purpose.

This mirrors the real architecture's split between the Ansys bridge (verifies
step completion) and the Tutorial client (drives the overlay/panel) -- see
CLAUDE.md / Student-Track-App-Build-Plan.md. guide_tut1.py should only need to
call verify_step(step) and act on the result; it shouldn't know HOW any given
step gets checked.

verify_step() dispatches on the step's `verify.type` field from tut1.json and
returns one of:
    True  -- verified, step is complete
    False -- checked, not complete yet
    None  -- no automatic check exists for this verify.type (caller should
             gate via manual confirmation instead of guessing)

Implemented so far: "window_appeared" (step 1: is the app's process running),
"window_title_excludes" (step 2: has the app's window title stopped saying
e.g. "Unsaved Project"), "ocr_text_present" (step 3: has a system block been
dropped onto the Project Schematic). Add a new `if vtype == "...":` branch
here -- not in guide_tut1.py -- as later steps bring new verify types (uia,
script, manual...) into play.
"""

try:
    import psutil
except ImportError:
    psutil = None

try:
    from pywinauto import Desktop
except ImportError:
    Desktop = None

import locate  # only for its OCR/region-finding capability (locate_text,
                # schematic_rect) -- "ocr_text_present" needs the same live
                # screen-reading machinery the locator already owns, so this
                # reuses it rather than re-implementing OCR here. Different
                # from the deliberate small-constant duplication elsewhere in
                # this file (APP_TITLES etc.) -- OCR is substantial shared
                # machinery, not a one-line mapping worth copying.

DEBUG = True  # print diagnostic lines to the console

# Maps a tut1.json `app` key to the real OS process name that means "this app
# is open". Confirmed against a live machine for workbench (AnsysFWW.exe);
# spaceclaim/mechanical are unconfirmed guesses -- fill in for real once we
# reach the steps that need them, the same way workbench was confirmed.
APP_PROCESS_NAMES = {
    "workbench": "AnsysFWW",
    "spaceclaim": "SpaceClaim",     # UNCONFIRMED -- verify when we get there
    "mechanical": "AnsysWBU",       # UNCONFIRMED -- verify when we get there
}

# Maps a tut1.json `app` key to a substring of that app's main window title --
# used for window_title_excludes checks (e.g. Workbench's title bar reads
# "Unsaved Project - Workbench" until the project is saved, then switches to
# the project name). Duplicated from locate.py's APP_TITLES on purpose --
# verify.py stays independent of locate.py's element-finding machinery.
APP_WINDOW_TITLES = {
    "workbench": "Workbench",
    "spaceclaim": "SpaceClaim",     # UNCONFIRMED -- verify when we get there
    "mechanical": "Mechanical",     # UNCONFIRMED -- verify when we get there
}


def process_running(name_fragment):
    """True if any running process's name contains `name_fragment`
    (case-insensitive). Checking the OS process list directly is simpler and
    more reliable than scanning window titles via UI Automation for a basic
    "is the app open" question -- confirmed on step 1, where the window-title
    approach was failing.
    """
    if not name_fragment or psutil is None:
        return False
    matched = None
    ansys_related = []
    try:
        for p in psutil.process_iter(["name"]):
            n = p.info.get("name") or ""
            if "ansys" in n.lower() or "spaceclaim" in n.lower():
                ansys_related.append(n)
            if name_fragment.lower() in n.lower():
                matched = n
    except Exception as e:
        if DEBUG:
            print(f"[debug] process_running failed: {e}")
        return False
    if DEBUG:
        print(f"[debug] process_running({name_fragment!r}) -> "
              f"{'MATCH ' + matched if matched else 'NOT FOUND'}; "
              f"ansys-related processes seen: {ansys_related}")
    return matched is not None


def window_appeared(app_key):
    """Checks whether the named app (a tut1.json `app` key) is open. Named to
    match verify.type == "window_appeared" in the JSON, even though the
    actual check is process-based now, not a window-title scan."""
    proc_name = APP_PROCESS_NAMES.get(app_key)
    if not proc_name:
        if DEBUG:
            print(f"[debug] window_appeared: no process name mapped for app={app_key!r}")
        return False
    return process_running(proc_name)


def app_window_title(app_key):
    """Returns the title text of the largest visible window matching
    `app_key`'s title hint, or None if no such window is open. Same
    largest-visible-match disambiguation as locate.py's _window(), since
    Application().connect() throws on 2+ title matches."""
    hint = APP_WINDOW_TITLES.get(app_key)
    if not hint or Desktop is None:
        return None
    candidates = []
    try:
        for w in Desktop(backend="uia").windows():
            try:
                title = w.window_text() or ""
                if hint.lower() not in title.lower():
                    continue
                if not w.is_visible():
                    continue
                rect = w.rectangle()
                area = rect.width() * rect.height()
            except Exception:
                continue
            if area > 0:
                candidates.append((area, title))
    except Exception as e:
        if DEBUG:
            print(f"[debug] app_window_title({app_key!r}): window enumeration failed: {e}")
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def window_title_excludes(v):
    """verify.type == "window_title_excludes": True once the app's window
    title no longer contains `text` -- e.g. Workbench's title bar drops
    "Unsaved Project" once the project has actually been saved."""
    app_key = v.get("app")
    needle = v.get("text", "")
    title = app_window_title(app_key)
    if title is None:
        if DEBUG:
            print(f"[debug] window_title_excludes: couldn't read window title for app={app_key!r}")
        return False
    ok = needle.lower() not in title.lower()
    if DEBUG:
        print(f"[debug] window_title_excludes: title={title!r} text={needle!r} -> {ok}")
    return ok


SCOPE_REGIONS = {"schematic": locate.schematic_rect}

# Per-check accumulator: (tuple(texts), scope) -> set of phrases ever
# confirmed present so far. Needed because a single tick's OCR pass can
# genuinely miss a phrase that's been read correctly on a previous tick
# (confirmed live: "Geometry"/"Model" dropped out of one read of an unchanged
# schematic block while "Engineering Data" etc. read fine, then the reverse
# happened on a later read) -- once a phrase has been seen, treat it as
# settled rather than re-litigating it every tick.
_ocr_found_cache = {}


def ocr_text_present(v):
    """verify.type == "ocr_text_present": True once every phrase in `texts`
    (or the single `text`) has been read on screen within `scope` (currently
    only "schematic" -> the Project Schematic canvas), at some point since
    this check started -- see _ocr_found_cache. Step 3 uses the row labels of
    the actual system block shown in the reference screenshot -- Engineering
    Data / Geometry / Model / Setup / Solution / Results -- rather than just
    "Static Structural" alone, so the check confirms the whole block matches,
    not just one row. ("Static Structural" itself is deliberately excluded:
    it's also the Toolbox's own permanent template row, so re-checking it
    would be a guaranteed false positive even before the drag happens.)"""
    texts = v.get("texts") or ([v["text"]] if v.get("text") else [])
    scope = v.get("scope")
    region_fn = SCOPE_REGIONS.get(scope)
    region = region_fn() if region_fn else None
    if not texts or region is None:
        if DEBUG:
            print(f"[debug] ocr_text_present: no texts or no {scope!r} region available")
        return False
    key = (tuple(texts), scope)
    confirmed = _ocr_found_cache.setdefault(key, set())
    still_missing = [t for t in texts if t not in confirmed]
    if still_missing:
        confirmed |= locate.texts_found(still_missing, region)
    ok = len(confirmed) == len(texts)
    if DEBUG:
        print(f"[debug] ocr_text_present: texts={texts} scope={scope!r} -> {ok} "
              f"(confirmed so far: {sorted(confirmed)})")
    return ok


def verify_step(step):
    """Dispatch `step`'s verify spec to the right checker. See module
    docstring for the True/False/None contract."""
    v = step.get("verify", {})
    vtype = v.get("type")
    if vtype == "window_appeared":
        return window_appeared(v.get("app"))
    if vtype == "window_title_excludes":
        return window_title_excludes(v)
    if vtype == "ocr_text_present":
        return ocr_text_present(v)
    if vtype in ("manual", "script"):
        # Intentionally no automatic check -- e.g. "did you save the file?"
        # can't be verified by inspecting the UI tree. The caller must gate
        # this step via an explicit manual-confirm control.
        return None
    if vtype == "uia":
        # Not implemented yet -- comes back when a step needs it (existence/
        # selection checks against the live UIA tree).
        if DEBUG:
            print(f"[debug] verify_step: 'uia' verify type not implemented yet "
                  f"for step {step.get('step_id')!r}")
        return None
    if DEBUG:
        print(f"[debug] verify_step: UNKNOWN verify.type {vtype!r} for step "
              f"{step.get('step_id')!r} -- check tut1.json for a typo")
    return None

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

Every step in tut1.json currently uses verify.type == "manual" (or a "script"/
"uia" type with no implementation yet) -- both fall through to the same
None/manual-confirm path below. Automatic checks (window_appeared,
window_title_excludes, ocr_text_present, row_status_icon, and a PyMechanical
gRPC integration for script engine="pymechanical") were built and DID work,
but were deliberately removed in favor of manual confirmation across the
board: continuing to chase OCR/UIA/gRPC reliability issues (panel-text
leaking into OCR captures, hue-range mis-calibration, untested PyMechanical
gRPC connectivity) wasn't worth the fragility for a student-facing pilot --
see tut1.json's _notes.manual_verify_switch_2026-06 for the full reasoning.
Add a new `if vtype == "...":` branch here -- not in guide_tut1.py -- if
automatic verification comes back for a specific step later.
"""

DEBUG = True  # print diagnostic lines to the console


def verify_step(step):
    """Dispatch `step`'s verify spec to the right checker. See module
    docstring for the True/False/None contract."""
    v = step.get("verify", {})
    vtype = v.get("type")
    if vtype in ("manual", "script"):
        # Intentionally no automatic check -- e.g. "did you save the file?"
        # can't be verified by inspecting the UI tree, OR (engine ==
        # "spaceclaim"/"pymechanical") no scripting integration is wired up
        # right now. The caller must gate this step via an explicit
        # manual-confirm control.
        return None
    if vtype == "uia":
        # Not implemented -- existence/selection checks against the live UIA
        # tree. Falls through to manual-confirm like "manual"/"script" above.
        if DEBUG:
            print(f"[debug] verify_step: 'uia' verify type not implemented "
                  f"for step {step.get('step_id')!r}")
        return None
    if DEBUG:
        print(f"[debug] verify_step: UNKNOWN verify.type {vtype!r} for step "
              f"{step.get('step_id')!r} -- check tut1.json for a typo")
    return None

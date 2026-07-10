"""
Validate a tutorial JSON file before running it in the guide.

Usage:
    .venv\\Scripts\\python tools\\validate_tutorial.py mock_server\\data\\tut2.json
    .venv\\Scripts\\python tools\\validate_tutorial.py FILE [FILE ...] [--strict]

Exit code 0 = usable (warnings allowed), 1 = has errors (or any warning with
--strict). ERROR means the guide would crash or silently misbehave on this
file; WARN means it will run but something looks wrong or incomplete.

Stdlib only -- no dependencies, runs on any Python 3.10+.

The rules here mirror exactly what the runtime consumes (spikes/guide_tut1.py,
locate.py, verify.py, report_verify.py). Field-by-field guidance for authors
lives in mock_server/data/README.md and the annotated _template.json.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR_FMT = "mock_server/data/images/{tutorial_id}/"

APPS = {"workbench", "spaceclaim", "discovery", "mechanical"}
SELECTOR_TYPES = {"uia", "ocr_text", "viewport", "window"}
HIGHLIGHT_TYPES = {"uia", "ocr_text", "instruction", "none"}
VERIFY_TYPES = {"manual", "uia", "script", "window_appeared"}
ACTION_KINDS = {
    "click", "right_click", "double_click", "menu_select", "text_entry",
    "drag", "draw", "select", "select_face", "launch", "close",
}
STEP_ID_RE = re.compile(r"^[a-z]{2}_[0-9]{2}_[a-z0-9_]+$")
RESERVED_STEP_IDS = {"report_01_upload"}  # synthetic step the guide appends itself

# Known keys per object; anything else (not starting with "_") is probably a
# typo -- the runtime ignores unknown keys silently, so we flag them here.
TOP_KEYS = {
    "tutorial_id", "version", "title", "problem", "report_checks", "apps",
    "runtime_steps", "sections",
}
SECTION_KEYS = {"section", "app", "steps"}
STEP_KEYS = {
    "step_id", "app", "title", "description", "selector", "highlight",
    "action", "launches", "verify", "hints", "source_image",
}
SELECTOR_KEYS = {"type", "name", "text", "scope", "via", "app"}
ACTION_KEYS = {"kind", "via", "then", "value"}
VERIFY_KEYS = {"type", "prompt", "engine", "check", "args", "target", "app"}
REPORT_CHECKS_KEYS = {"required_sections", "preferred_sections",
                      "must_contain", "expected_result"}
EXPECTED_RESULT_KEYS = {"value", "tolerance", "units", "aliases"}


class Findings:
    def __init__(self):
        self.items = []  # (severity, where, message)

    def error(self, where, msg):
        self.items.append(("ERROR", where, msg))

    def warn(self, where, msg):
        self.items.append(("WARN", where, msg))

    @property
    def errors(self):
        return [f for f in self.items if f[0] == "ERROR"]

    @property
    def warnings(self):
        return [f for f in self.items if f[0] == "WARN"]


def _public_keys(obj):
    return {k for k in obj if not k.startswith("_")}


def _check_unknown_keys(f, where, obj, allowed):
    unknown = _public_keys(obj) - allowed
    if unknown:
        f.warn(where, f"unknown key(s) {sorted(unknown)} -- typo? "
                      f"(keys starting with _ are always allowed as comments)")


def _require_str(f, where, obj, key):
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        f.error(where, f"'{key}' is required and must be a non-empty string")
        return None
    return val


def validate(path: Path) -> Findings:
    f = Findings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        f.error("$", f"cannot read file: {exc}")
        return f
    except json.JSONDecodeError as exc:
        f.error("$", f"not valid JSON: {exc}")
        return f
    if not isinstance(data, dict):
        f.error("$", "top level must be a JSON object")
        return f

    _check_unknown_keys(f, "$", data, TOP_KEYS)

    # --- top-level contract fields (runtime doesn't read these, other
    # modules will -- missing ones are warnings, not crashes) ---
    for key in ("tutorial_id", "title"):
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            f.warn("$", f"'{key}' should be a non-empty string")
    if not isinstance(data.get("version"), int):
        f.warn("$", "'version' should be an integer (start at 1)")

    apps = data.get("apps")
    if not isinstance(apps, list) or not apps:
        f.warn("$", "'apps' should list the Ansys apps this tutorial spans")
        apps = []
    for a in apps:
        if a not in APPS:
            f.error("$", f"apps entry '{a}' is not one of {sorted(APPS)}")
    app_set = {a for a in apps if a in APPS}

    # --- sections / steps (this is what the guide actually runs) ---
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        f.error("$", "'sections' is required and must be a non-empty array")
        return f

    seen_ids = {}
    all_steps = []
    for si, sec in enumerate(sections):
        s_where = f"sections[{si}]"
        if not isinstance(sec, dict):
            f.error(s_where, "section must be an object")
            continue
        _check_unknown_keys(f, s_where, sec, SECTION_KEYS)
        _require_str(f, s_where, sec, "section")
        sec_app = sec.get("app")
        if sec_app is not None and app_set and sec_app not in app_set:
            f.error(s_where, f"section app '{sec_app}' is not in top-level apps {sorted(app_set)}")
        steps = sec.get("steps")
        if not isinstance(steps, list) or not steps:
            f.error(s_where, "'steps' is required and must be a non-empty array")
            continue
        for ti, st in enumerate(steps):
            if not isinstance(st, dict):
                f.error(f"{s_where}.steps[{ti}]", "step must be an object")
                continue
            where = st.get("step_id") or f"{s_where}.steps[{ti}]"
            all_steps.append((where, st))
            sid = st.get("step_id")
            if isinstance(sid, str) and sid in seen_ids:
                f.error(where, f"duplicate step_id (also in {seen_ids[sid]})")
            elif isinstance(sid, str):
                seen_ids[sid] = s_where
            if isinstance(sid, str) and sid in RESERVED_STEP_IDS:
                f.error(where, f"step_id '{sid}' is reserved -- the guide appends "
                               f"this synthetic step itself when report_checks is present")

    for where, st in all_steps:
        _validate_step(f, where, st, app_set, data)

    _validate_images(f, data, all_steps, path.stem)

    # --- runtime_steps (optional; selects/orders which steps run) ---
    runtime_steps = data.get("runtime_steps")
    if runtime_steps is not None:
        if not isinstance(runtime_steps, list) or not all(isinstance(s, str) for s in runtime_steps):
            f.error("$", "'runtime_steps' must be an array of step_id strings")
        else:
            missing = [sid for sid in runtime_steps if sid not in seen_ids]
            if missing:
                f.error("$", f"runtime_steps references step_id(s) not in the tutorial: {missing}")
            dupes = {sid for sid in runtime_steps if runtime_steps.count(sid) > 1}
            if dupes:
                f.warn("$", f"runtime_steps lists step_id(s) more than once: {sorted(dupes)}")
            unused = [sid for sid in seen_ids if sid not in runtime_steps]
            if unused:
                f.warn("$", f"{len(unused)} authored step(s) not in runtime_steps "
                            f"(won't run): {unused[:5]}{'...' if len(unused) > 5 else ''}")

    _validate_report_checks(f, data)
    return f


def _validate_step(f, where, st, app_set, data):
    _check_unknown_keys(f, where, st, STEP_KEYS)

    # Crash spine: the guide indexes these directly on every rendered step.
    _require_str(f, where, st, "step_id")
    _require_str(f, where, st, "title")
    _require_str(f, where, st, "description")

    sid = st.get("step_id")
    if isinstance(sid, str) and not STEP_ID_RE.match(sid):
        f.warn(where, "step_id doesn't match the '{app}_{NN}_{slug}' convention "
                      "(e.g. wb_01_open, me_04_generate_mesh)")

    app = st.get("app")
    if not isinstance(app, str) or app not in APPS:
        f.error(where, f"'app' is required and must be one of {sorted(APPS)}")
    elif app_set and app not in app_set:
        f.error(where, f"app '{app}' is not in top-level apps {sorted(app_set)}")

    launches = st.get("launches")
    if launches is not None and app_set and launches not in app_set:
        f.error(where, f"launches '{launches}' is not in top-level apps {sorted(app_set)}")

    highlight = st.get("highlight")
    if highlight not in HIGHLIGHT_TYPES:
        f.error(where, f"'highlight' is required and must be one of {sorted(HIGHLIGHT_TYPES)}")

    sel = st.get("selector")
    if sel is None:
        if highlight in ("uia", "ocr_text"):
            f.error(where, f"highlight '{highlight}' needs a selector")
        sel = {}
    elif not isinstance(sel, dict):
        f.error(where, "'selector' must be an object")
        sel = {}
    else:
        _check_unknown_keys(f, f"{where}.selector", sel, SELECTOR_KEYS)
        stype = sel.get("type")
        if stype is not None and stype not in SELECTOR_TYPES:
            f.error(where, f"selector.type '{stype}' is not one of {sorted(SELECTOR_TYPES)}")
        scope = sel.get("scope")
        if scope is not None and scope != "schematic":
            f.warn(where, f"selector.scope '{scope}' -- only 'schematic' does anything today")

    # highlight/selector pairings the runtime depends on
    if highlight == "uia":
        if sel.get("type") != "uia":
            f.error(where, "highlight 'uia' requires selector.type 'uia'")
        if not sel.get("name"):
            f.error(where, "highlight 'uia' requires selector.name (the element's display name)")
    elif highlight == "ocr_text":
        if not (sel.get("text") or sel.get("name")):
            f.error(where, "highlight 'ocr_text' requires selector.text (the on-screen text to find)")
    elif highlight == "instruction":
        if not st.get("source_image"):
            f.error(where, "highlight 'instruction' requires source_image (the reference screenshot shown instead of a live box)")

    action = st.get("action")
    if action is not None:
        if not isinstance(action, dict):
            f.error(where, "'action' must be an object")
        else:
            _check_unknown_keys(f, f"{where}.action", action, ACTION_KEYS)
            kind = action.get("kind")
            if kind is not None and kind not in ACTION_KINDS:
                f.warn(where, f"action.kind '{kind}' is not a known kind {sorted(ACTION_KINDS)} "
                              f"(actions are documentation -- fine if intentional)")

    verify = st.get("verify")
    if not isinstance(verify, dict):
        f.error(where, "'verify' is required and must be an object with a 'type'")
    else:
        _check_unknown_keys(f, f"{where}.verify", verify, VERIFY_KEYS)
        vtype = verify.get("type")
        if vtype not in VERIFY_TYPES:
            f.error(where, f"verify.type '{vtype}' is not one of {sorted(VERIFY_TYPES)}")
        elif vtype == "manual" and not verify.get("prompt"):
            f.warn(where, "manual verify should carry a 'prompt' (the confirm question)")
        elif vtype == "script" and not (verify.get("engine") and verify.get("check")):
            f.error(where, "script verify requires 'engine' (pymechanical|spaceclaim) and 'check'")
        elif vtype == "uia" and not (verify.get("check") and verify.get("target")):
            f.error(where, "uia verify requires 'check' and 'target'")
        elif vtype == "window_appeared":
            target_app = verify.get("app") or verify.get("target")
            if app_set and target_app not in app_set:
                f.error(where, f"window_appeared verify needs 'app' set to one of {sorted(app_set)}")

    hints = st.get("hints")
    if hints is not None and (not isinstance(hints, list)
                              or not all(isinstance(h, str) for h in hints)):
        f.error(where, "'hints' must be an array of strings")
    elif not hints and highlight != "none":
        f.warn(where, "no hints -- the panel shows the first hint under the description; add at least one")


def _validate_report_checks(f, data):
    rc = data.get("report_checks")
    if rc is None:
        f.warn("$", "no report_checks -- the guide won't add the report-upload "
                    "checkpoint at the end (fine if this tutorial has no report)")
        return
    if not isinstance(rc, dict):
        f.error("$", "'report_checks' must be an object")
        return
    _check_unknown_keys(f, "$.report_checks", rc, REPORT_CHECKS_KEYS)
    for key in ("required_sections", "preferred_sections", "must_contain"):
        val = rc.get(key)
        if val is not None and (not isinstance(val, list)
                                or not all(isinstance(s, str) for s in val)):
            f.error("$.report_checks", f"'{key}' must be an array of strings")
    if not rc.get("required_sections"):
        f.warn("$.report_checks", "empty/missing required_sections -- every uploaded report will pass")

    er = rc.get("expected_result")
    if er is not None:
        if not isinstance(er, dict):
            f.error("$.report_checks", "'expected_result' must be an object")
        else:
            _check_unknown_keys(f, "$.report_checks.expected_result", er, EXPECTED_RESULT_KEYS)
            if not isinstance(er.get("value"), (int, float)):
                f.error("$.report_checks", "expected_result.value must be a number")
            if not isinstance(er.get("tolerance"), (int, float)):
                f.warn("$.report_checks", "expected_result has no numeric tolerance -- "
                                          "an exact float match almost never passes")


def _validate_images(f, data, all_steps, file_stem):
    # Folder may be named after the JSON file (tut1.json -> images/tut1/) or
    # the tutorial_id -- either satisfies the convention.
    convention_dirs = tuple({
        IMAGES_DIR_FMT.format(tutorial_id=file_stem),
        IMAGES_DIR_FMT.format(tutorial_id=data.get("tutorial_id", "<tutorial_id>")),
    })
    missing, off_convention = [], []
    for where, st in all_steps:
        img = st.get("source_image")
        if not img:
            continue
        if not isinstance(img, str):
            f.error(where, "'source_image' must be a string path (repo-root-relative) or null")
            continue
        if not (REPO_ROOT / img).is_file():
            missing.append(where)
        elif not img.replace("\\", "/").startswith(convention_dirs):
            off_convention.append(where)
    if missing:
        f.warn("$", f"{len(missing)} source_image file(s) not found under the repo root "
                    f"(steps {missing[:4]}{'...' if len(missing) > 4 else ''}) -- "
                    f"the panel will show no reference image for these")
    if off_convention:
        f.warn("$", f"{len(off_convention)} source_image path(s) outside the convention "
                    f"'{convention_dirs[0]}' (steps {off_convention[:4]}{'...' if len(off_convention) > 4 else ''})")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    strict = "--strict" in argv
    if not args:
        print(__doc__.strip())
        return 2
    overall_fail = False
    for arg in args:
        path = Path(arg)
        if not path.is_file() and (REPO_ROOT / arg).is_file():
            path = REPO_ROOT / arg
        findings = validate(path)
        for sev, where, msg in findings.items:
            print(f"{sev:5}  {where}: {msg}")
        n_err, n_warn = len(findings.errors), len(findings.warnings)
        failed = bool(n_err) or (strict and bool(n_warn))
        overall_fail |= failed
        print(f"{path.name}: {n_err} error(s), {n_warn} warning(s) -- "
              f"{'FAIL' if failed else 'PASS'}")
    return 1 if overall_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

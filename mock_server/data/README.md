# Authoring a tutorial

A tutorial is **one JSON file** in this folder. The guide app reads it directly —
adding a new tutorial requires **no code changes**.

## Quick start

```
1. Copy _template.json  →  mock_server/data/<tutorial_id>.json   (e.g. tut2_plate_with_hole.json)
2. Fill it in (the _comment keys in the template explain every pattern; tut1.json is a full real example)
3. Put reference screenshots in mock_server/data/images/<tutorial_id>/
4. Check it:   .venv\Scripts\python tools\validate_tutorial.py mock_server\data\<file>.json
5. Run it:     .venv\Scripts\python spikes\guide_tut1.py <tutorial_id>
```

The validator must report `0 error(s)` before you test live. Warnings are
advice — fix them when you can.

## Structure

```
tutorial
├─ tutorial_id, version, title, problem, apps[]                    metadata
├─ report_checks          rubric for the end-of-tutorial report upload (optional)
├─ runtime_steps          OPTIONAL: which step_ids run, in what order
│                         (omit → every step runs in document order)
└─ sections[]             pedagogical units ("Set up the analysis", ...)
   └─ steps[]             ONE student action each
```

Every step: `step_id`, `app`, `title`, `description`, `selector`, `highlight`,
`action`, `verify`, `hints`, `source_image`. Keys starting with `_` anywhere
are comments — the app and validator ignore them.

## The one decision that matters: selector + highlight

Where is the thing the student must click? That decides the pair:

| Target | selector.type | highlight | Notes |
|---|---|---|---|
| Ribbon, menu, tree item | `uia` | `uia` | Live box via UI Automation. `name` = exact display name; `via` = parent menu to open first (e.g. File → Save As). |
| Workbench **Toolbox** or **Project Schematic** | `ocr_text` | `ocr_text` | These panels are **invisible to UIA/win32** (confirmed — don't retry). `text` = the on-screen label; add `"scope": "schematic"` to search the schematic block instead of the Toolbox. |
| Inside the **3D viewport** (pick a face, sketch, rotate) | `viewport` | `instruction` | Nothing in the 3D window is automatable. Provide `source_image` — the panel shows your screenshot instead of a live box. |
| Launching/closing an app | `window` | `none` | No box; the description carries the instruction. Set `launches` when the step opens another app. |

Selector display names are version-coupled — verify them against **Ansys 2025 R2**.

## verify

In the current pilot **every step ends with a manual "Mark step complete"
button**, whatever you write (automatic checks were built, worked, and were
deliberately removed as too fragile — see tut1.json `_notes.manual_verify_switch_2026-06`).
Still author the real check; the runtime will grow into it:

- `manual` + `prompt` — always safe. The prompt is the confirm question.
- `script` + `engine` (`pymechanical` | `spaceclaim`) + `check` — authoritative model-state check.
- `uia` + `check` + `target` — UI-tree check.
- `window_appeared` + `app` — app-transition steps.

## report_checks

Grades the report the student uploads at the end (this checkpoint appears
only when `report_checks` exists):

- `required_sections`, `must_contain` — hard checks; the student can't finish until they pass.
- `preferred_sections` — warnings only.
- `expected_result` `{value, tolerance, units, aliases}` — checks the numeric
  answer within ±tolerance.

## Conventions

- **step_id**: `{app}_{NN}_{slug}` — `wb_03_add_static_structural`. Prefixes: wb/sc/ed/me/re.
- **One action per step.** "Expand Geometry, select Solid, set the material" is three steps.
- **hints**: the panel shows the **first** hint under the description; order most-helpful-first.
- **Images**: `mock_server/data/images/<tutorial>/<step_id>.png` — folder named after
  the tutorial file (`tut1.json` → `images/tut1/`). Cropped and annotated.
- **`_notes`**: when live testing forces a strategy change (selector, verify),
  record why with a dated key (`something_2026-07`) so the next author doesn't
  re-diagnose it. tut1.json's `_notes` is the model.

## Before you hand it off

- [ ] `validate_tutorial.py` → 0 errors
- [ ] Walked through live on a lab PC (2025 R2): every `uia`/`ocr_text` box finds its element
- [ ] Every `instruction` step shows its screenshot
- [ ] Uploaded a real generated report → `report_checks` passes on a correct report, fails on a wrong one

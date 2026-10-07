# Desktop guide

The panel that runs on the lab PC, on top of Ansys: it shows the current step,
highlights the element to interact with, and reports progress back to the hub.

| File | Purpose |
|---|---|
| `guide_tut1.py` | The guide itself — step panel, highlight overlay, progress reporting |
| `locate.py` | Finds on-screen elements: UI Automation first, OCR fallback (`tessdata/`) |
| `verify.py` | Checks a step is done, per the step's `verify` block |
| `report_verify.py` | Re-exports the server's report rubric checks for the local pre-check |

Students normally start it from the hub's **Launch desktop guide** button, which
needs a one-time per-PC registration (no admin rights):

```
.venv\Scripts\python tools\register_guide_protocol.py     # --unregister reverses it
```

## Running it directly

```
pip install pywinauto ansys-mechanical-core pynput pyqt6
.venv\Scripts\python student_app\guide_tut1.py <tutorial_id>
```

It runs any tutorial in `content/data/` with no code changes. Author new ones from
`content/data/_template.json` following `content/data/README.md`, and check them with
`python tools/validate_tutorial.py <file>` before testing on a lab PC.

## Notes

- **Window titles** (`TITLE_HINT`, `APP_TITLES`) are version-coupled; they target
  Ansys 2025 R2.
- UI Automation cannot see Workbench's Toolbox or Project Schematic — hence the
  OCR fallback in `locate.py`. See `_notes` in `content/data/tut1.json` for the
  finding behind that.
- Step reference images come from the repo (`content/data/images/`) or are
  downloaded from the hub by `tools/guide_launcher.py` when the instructor
  uploaded them through the web editor.
- These dependencies are deliberately not in `requirements.txt`: the hub does not
  need PyQt6 or pywinauto, and only lab PCs run this.

# Ansys Tutoring System — ME-UY 4214

AI-assisted tutoring system for NYU's ME-UY 4214 (Finite Element Analysis lab).
Built as a course/research deliverable (AI in Education Seed Grant; pilot Fall 2026).

## Status

Greenfield. Currently building the **Student Interaction Track App** (the
student-side module) first — it's the most important module and the integration
point the others feed.

## Source of truth

`ME-UY 4214 Tutoring System - Architecture Design v2.docx` — full 5-module system
architecture (v0.2), the authoritative spec. Do not duplicate it here; update it
and link.

## System shape (one paragraph)

Five modules across two machines, REST over NYU LAN, fully local (no cloud in
normal operation). Four instructor-side modules run on the instructor desktop
(Tutorial Creating, Tutorials & Quizzes, Evaluating, Ansys Help Chatbot). One
student-side module — the **Student Interaction Track App** — runs on each lab PC
(sub-components: Tutorial client, Ansys bridge, Sync service).

## Critical domain facts (these bite if you don't know them)

- **A single tutorial spans THREE Ansys apps, one child at a time, launched from
  Workbench:** Ansys Workbench (hub) → Ansys Discovery (geometry) → back to
  Workbench → Ansys Mechanical (FEA/solve). The Ansys bridge is **app-aware**:
  it tracks the current target app, detects window appear/close on transitions,
  queries the right UI Automation tree, and verifies per-app.
- **Verification access differs per app.** Mechanical is strongest (PyMechanical /
  gRPC). Discovery has a SpaceClaim-derived Python scripting API (reachability
  TBD). Workbench is likely UIA-only. **UIA is the common denominator**; the
  verifier degrades gracefully via each step's `verify.type`.
- **Authoritative state verification:** step completion is judged against real
  model state (PyAnsys), not UI events alone, wherever model-state access exists.
- **Local-first + FERPA by construction.** Student data never leaves NYU
  infrastructure. Logs use opaque session tokens, not NetIDs/names. No cloud LLM
  touches student data. Keep this invariant in any new code.
- **Windows-only, Ansys 2025 R2.** Pin to this version; UIA selectors are version-
  coupled. Lab PCs have no GPU; server-side AI runs on the instructor desktop GPU.

## Tech stack (Student Interaction Track App)

Python 3.11+ · PyQt6 (transparent click-through overlay) · pynput (input capture)
· pywinauto / uiautomation (UI Automation) · ansys-mechanical-core / PyMechanical
(model state) · httpx (REST) · sqlite3 (disk-backed event buffer) · FastAPI
(the hub serves tutorials, quizzes and progress) · pytest + pytest-qt.

## Architecture conventions

- **Typed-interface seams.** Sub-components depend only on Protocols
  (`BridgeProtocol`, `SyncProtocol`), so the client is tested against `FakeBridge`
  / `FakeSync` with no Ansys and no server. Keep this boundary clean.
- **Threading ownership is strict.** Main thread owns the PyQt6 event loop AND all
  UIA queries (COM thread affinity). pynput runs on its own listener thread; sync
  upload is a background thread. Never touch Qt widgets from worker threads — use
  signals/slots or `QMetaObject.invokeMethod`.
- **Tutorial JSON is the cross-module contract.** Steps carry `app`,
  `selector`, `action`, `verify` (`uia` | `script` | `window_appeared`), and
  optional `launches` for app-transition steps. Tutorials are JSON-only: the
  guide runs any `content/data/<tutorial_id>.json` with no code changes
  (`python student_app/guide_tut1.py <tutorial_id>`). Author new ones from
  `content/data/_template.json` per `content/data/README.md`, and
  check them with `python tools/validate_tutorial.py <file>` before testing.
- `student_app/` is the desktop guide that runs on lab PCs; `tools/` holds the
  author- and launcher-facing utilities. Both ship.

## Repo layout

| Path | Purpose |
|---|---|
| `server/` | FastAPI hub: routers, services, SQLite schema |
| `webapp/` | React SPA — student runner and instructor dashboards |
| `student_app/` | Desktop guide that runs on lab PCs, over Ansys |
| `content/data/` | Authored tutorials, quizzes, step images + authoring README |
| `compass/` | Ansys-doc retrieval + local LLM for the chat assistant (off unless `ENABLE_AI=1`) |
| `tools/` | Validator, guide launcher, protocol registration |
| `deploy/` | Docker Compose, nginx and the NYU deployment runbook |
| `tests/` | pytest — the hub is fully testable without Ansys or a model |

## Commands

- Install: `pip install -r requirements.txt` (and `cd webapp && npm install && npm run build`)
- Run the hub: `python -m uvicorn server.app:app --port 8000`
- Run the desktop guide: `python student_app/guide_tut1.py <tutorial_id>` (needs Ansys)
- Tests (no Ansys, no model, no Ollama): `pytest`
- Validate an authored tutorial: `python tools/validate_tutorial.py <file>`

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.
When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

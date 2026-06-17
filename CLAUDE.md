# Ansys Tutoring System — ME-UY 4214

AI-assisted tutoring system for NYU's ME-UY 4214 (Finite Element Analysis lab).
Built as a course/research deliverable (AI in Education Seed Grant; pilot Fall 2026).

## Status

Greenfield. Currently building the **Student Interaction Track App** (the
student-side module) first — it's the most important module and the integration
point the others feed.

## Source of truth (read these before planning work)

- `Student-Track-App-Build-Plan.md` — the build plan for the module in progress
  (approach, phases, contracts, the Phase 0 spike). **Start here.**
- `ME-UY 4214 Tutoring System - Architecture Design v2.docx` — full 5-module
  system architecture (v0.2). The authoritative spec.

Do not duplicate these here; update them and link.

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
(mock server standing in for Tutorials & Quizzes during dev) · pytest + pytest-qt.

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
  optional `launches` for app-transition steps.
- Spike/throwaway code lives in `spikes/`; it is not shipped.

## Planned repo layout

| Path | Purpose |
|---|---|
| `student_app/runtime/` | State machine + session |
| `student_app/overlay/` | PyQt6 transparent overlay (highlight, step panel, hint) |
| `student_app/bridge/` | App-aware Ansys I/O (watcher, verifier, locator) + fakes |
| `student_app/sync/` | API client, disk-backed event logger, local cache + fakes |
| `student_app/quiz/` | Multiple-choice quiz runner |
| `mock_server/` | FastAPI stand-in for Tutorials & Quizzes |
| `spikes/` | Phase 0 throwaway probes |
| `tests/` | pytest (client testable without Ansys via fakes) |

## Commands (planned — wire up as code lands)

- Install: `pip install -r requirements.txt`
- Run mock server: `uvicorn mock_server.main:app --reload`
- Run app: `python -m student_app.app`
- Tests (no Ansys needed for client tests): `pytest`
- Bridge integration tests require Ansys; mark and skip in CI.

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

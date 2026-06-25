# Student Interaction Track App — Build Plan

**Module:** Student Interaction Track App (student-side, runs on each lab PC)
**Parent system:** Ansys Tutoring System (ME-UY 4214), v0.2 architecture
**Build approach:** A — bridge spike first, then clean vertical slices
**Goal:** Demonstrably-working, documented module for the course/research deliverable
**Date:** 2026-06-16

---

## 1. Scope of this plan

We build **only** the Student Interaction Track App, first. The other four
modules (Tutorial Creating, Tutorials & Quizzes, Evaluating, Chatbot) are out of
scope here, but two of them define contracts we must honor now:

- **Tutorials & Quizzes Module** → the REST contract the Sync service calls.
  It doesn't exist yet, so we stand up a tiny **mock server** that implements
  the documented endpoints. That mock is the integration seam; when the real
  module ships, the student app shouldn't need to change.
- **Tutorial Creating Module** → produces the tutorial JSON. It doesn't exist
  yet, so we **hand-author one tutorial JSON** ("Apply Fixed Support") to drive
  development.

The app's three sub-components, per the architecture doc:

| Sub-component | Responsibility |
|---|---|
| **Tutorial client** | Runtime state machine (7 states) + guidance overlay + quiz runner |
| **Ansys bridge** | Action watcher (pynput+UIA), state verifier (UIA+PyAnsys), element locator (10 Hz UIA polling) |
| **Sync service** | API client, disk-backed event logger, local cache |

---

## 2. Tech stack (concrete library choices)

All Windows, all local. Python 3.11+.

| Concern | Library | Notes |
|---|---|---|
| GUI / overlay | **PyQt6** | Transparent, frameless, always-on-top window. Per-region click-through is the hard part (see §5, Probe 4). |
| Input capture | **pynput** | Global mouse/keyboard hooks on its own listener thread. |
| UI Automation | **pywinauto** (primary) or **uiautomation** | Read Ansys's UIA element tree, names, automation IDs, bounding boxes. COM has thread affinity — all UIA calls on one thread. |
| Ansys model state | **ansys-mechanical-core** (PyMechanical) | Attaches to a running Mechanical session over gRPC; reads authoritative model state (geometry, BCs, mesh, solve status). |
| HTTP client | **httpx** | Retry/backoff/timeout/auth wrapper in the API client. |
| Event buffer | stdlib **sqlite3** (or JSONL) | Disk-backed queue; survives crashes and outages. |
| Local cache | JSON on disk | Versioned tutorials/quizzes/FAQs. |
| Mock server | **FastAPI + uvicorn** | Matches the documented server stack so the contract is real, not faked. |
| Tests | **pytest** + **pytest-qt** | Fakes for bridge/sync let the client be tested without Ansys. |

**Key technical reality to confirm in the spike:** in each Ansys app, the ribbon,
tree, and menus are largely exposed to UI Automation, but the **3D graphics
viewport is a render surface UIA cannot see into**. That means: highlight and
"what was clicked" work for ribbon/tree/menu elements via UIA, but anything that
happens *inside the geometry window* (picking a face, rotating) must be verified
through **model state** (PyMechanical etc.), not UIA. This is exactly why the doc
splits "fast UIA checks" from "authoritative PyAnsys checks." Validating this
split — **per app** — is a primary goal of Phase 0. See §2A: a tutorial spans
three apps, and this split holds differently in each.

---

## 2A. Multi-application model (a tutorial spans three Ansys apps)

A single tutorial runs across **three** Ansys applications, launched **one child
at a time from Workbench**:

1. **Ansys Workbench** — the project hub. The tutorial starts here. The student
   opens child apps from the project schematic (double-click *Geometry* →
   Discovery; double-click *Model* → Mechanical).
2. **Ansys Discovery** — opened at the geometry step. Build the 3D model.
3. **Ansys Mechanical** — opened at the model step. Materials, BCs, mesh, solve.

**Lifecycle (confirmed):** one child app at a time. Workbench stays open as the
hub; Discovery and Mechanical do not coexist. Flow: Workbench → Discovery → (back
to Workbench) → Mechanical.

**This makes the Ansys bridge app-aware.** It's no longer one bridge to one app:

- **Current target app.** The bridge tracks which app the current step targets
  (`workbench` | `discovery` | `mechanical`) and points the action watcher,
  element locator, and overlay at *that app's* window.
- **App-transition steps.** A step can launch a child app. The runtime enters a
  transition: highlight the launch action in Workbench, then **wait for the new
  app window to appear** (poll by process name / window title) before resuming
  highlighting in the new app. Reverse on close. The overlay must re-anchor to
  the newly-focused window.
- **Three separate UIA trees.** The watcher/locator query the UIA tree of the
  currently-foreground app, keyed by its process.

**Verification access per app is UNKNOWN right now** — so Phase 0 must discover
it for all three (see §5). Expected landscape:

| App | Likely model-state access | Fallback |
|---|---|---|
| Mechanical | **PyMechanical** (`ansys-mechanical-core`, gRPC) — strongest | UIA |
| Discovery | Python scripting API (SpaceClaim-derived); reachability TBD | UIA |
| Workbench | Mostly journaling (`wbjn`/IronPython) + UIA; likely UIA-only live | UIA |

**UIA is the common denominator across all three.** The State verifier must
**degrade gracefully**: use model-state scripting where it exists (strongest in
Mechanical), fall back to UIA checks where it doesn't (likely Workbench). Each
step's `verify` spec names which path to use.

---

## 3. The contracts (define these before coding)

### 3.1 Internal typed interfaces (so sub-components are testable in isolation)

```python
# bridge -> runtime
App = Literal["workbench", "discovery", "mechanical"]

@dataclass
class SemanticAction:
    app: App             # which app the action occurred in
    kind: str            # "click" | "key" | "menu_select" | ...
    target_id: str|None  # UIA automation id, if identifiable
    target_name: str|None
    raw: dict            # original pynput event, screen coords

class VerificationResult:
    passed: bool
    failed_check: str|None     # which check failed
    diagnostic: str|None       # human-readable, drives the hint balloon

class ElementBox:
    x: int; y: int; w: int; h: int   # screen-space, for the highlight renderer

# runtime depends ONLY on these protocols:
class BridgeProtocol(Protocol):
    def set_target_app(self, app: App) -> None: ...        # route to a given app's adapter
    def wait_for_app(self, app: App, timeout: float) -> bool: ...  # transition / LAUNCHING state
    def subscribe_actions(self, cb) -> None: ...
    # Verification is split by cost (eng-review decision 1):
    #   verify_fast  — UIA checks, synchronous, main thread (COM-bound, cheap)
    #   verify_async — slow `script` checks (pymechanical/discovery) on a worker
    #                  thread; result delivered via callback so the UI never
    #                  blocks during VERIFYING.
    def verify_fast(self, app: App, check_spec: dict) -> VerificationResult: ...
    def verify_async(self, app: App, check_spec: dict,
                     cb: Callable[[VerificationResult], None]) -> None: ...
    def locate(self, app: App, selector: dict) -> ElementBox|None: ...  # cached; see §8

class SyncProtocol(Protocol):
    def fetch_tutorial(self, tutorial_id: str) -> dict: ...
    def log_event(self, event: dict) -> None: ...
    def submit_quiz(self, result: dict) -> None: ...
```

These protocols are what let us build the client against a **FakeBridge** /
**FakeSync** and swap in real implementations later. They are the seam between
Approach A's spike output and the clean architecture.

### 3.2 REST contract (mock server implements; real module honors later)

From the doc:

```
GET  /tutorials?product=mechanical&is_mandatory=true
GET  /tutorials/{tutorial_id}
GET  /tutorials/{tutorial_id}/quiz
GET  /tutorials/{tutorial_id}/faqs
POST /events                       # event ingestion (Evaluating Module)
POST /quizzes/{quiz_id}/submit     # quiz results
```

### 3.3 Tutorial JSON schema (hand-author "Apply Fixed Support")

Each step carries an **`app`** field (which of the three apps it targets) and may
be an **app-transition step** (`launches` the next app; runtime waits for its
window before proceeding).

```json
{
  "tutorial_id": "wk03_fixed_support",
  "version": 1,
  "product": "mechanical",
  "is_mandatory": true,
  "title": "Static Structural: Fixed Support",
  "quiz_id": "wk03_fixed_support_quiz",
  "steps": [
    {
      "step_id": "s1",
      "app": "workbench",
      "title": "Add a Static Structural analysis system",
      "description": "Drag 'Static Structural' from the Toolbox onto the Project Schematic.",
      "selector": { "type": "uia", "name": "Static Structural" },
      "action": { "kind": "drag" },
      "verify": { "type": "uia", "check": "exists", "target": "Static Structural" },
      "hints": ["It's in the Analysis Systems group of the Toolbox."]
    },
    {
      "step_id": "s3",
      "app": "workbench",
      "title": "Open the geometry editor",
      "description": "Double-click the 'Geometry' cell to open Ansys Discovery.",
      "selector": { "type": "uia", "name": "Geometry" },
      "action": { "kind": "double_click" },
      "launches": "discovery",
      "verify": { "type": "window_appeared", "app": "discovery" },
      "hints": ["The Geometry cell is the 3rd row of the schematic."]
    },
    {
      "step_id": "s4",
      "app": "discovery",
      "title": "Create the beam body",
      "description": "Sketch a rectangle and pull it into a solid.",
      "selector": { "type": "uia", "name": "Pull" },
      "action": { "kind": "click" },
      "verify": { "type": "script", "engine": "discovery", "check": "body_count", "args": {"min": 1} },
      "hints": ["Sketch first, then use Pull to extrude."]
    },
    {
      "step_id": "s7",
      "app": "mechanical",
      "title": "Insert a Fixed Support",
      "description": "Right-click a face, then Insert > Fixed Support.",
      "selector": { "type": "uia", "name": "Fixed Support" },
      "action": { "kind": "menu_select" },
      "verify": { "type": "script", "engine": "pymechanical", "check": "bc_exists", "args": {"type": "Fixed Support"} },
      "hints": ["Select a face first.", "Right-click opens the insert menu."]
    }
  ]
}
```

Note the three `verify.type` patterns: `uia` (UI-tree check, works everywhere),
`script` with an `engine` (`pymechanical` / `discovery` — authoritative model
state, where available), and `window_appeared` (the transition check). The
`engine`/`type` chosen per step is what lets the verifier degrade gracefully when
an app only supports UIA.

---

## 4. Repo layout

```
tutoring-app-2/
  student_app/
    __init__.py
    runtime/            # state machine, session model
      state_machine.py
      session.py
    overlay/            # PyQt6 transparent window
      window.py
      highlight.py
      step_panel.py
      hint_balloon.py
    bridge/             # app-aware Ansys I/O
      protocol.py       # BridgeProtocol + dataclasses
      action_watcher.py # raw input -> SemanticAction via the current adapter
      state_verifier.py # verify_fast (UIA, main) + verify_async (script, worker)
      element_locator.py# cache + event-driven re-query (not blind 10 Hz)
      adapters/         # per-app strategy (eng-review decision 4)
        base.py         # AppAdapter protocol: locate / verify / identify_window
        workbench.py    # UIA-only
        discovery.py    # Discovery scripting + UIA
        mechanical.py   # PyMechanical + UIA
      fake_bridge.py    # scripted events + canned results for tests
    sync/
      protocol.py
      api_client.py
      event_logger.py
      cache.py
      fake_sync.py
    quiz/
      runner.py
    app.py              # wires everything, owns threads
  mock_server/          # FastAPI stand-in for Tutorials & Quizzes
    main.py
    data/               # hand-authored tutorial + quiz JSON
  spikes/               # Phase 0 throwaway probes (kept for the record, not shipped)
  tests/
  docs/
```

---

## 5. Phase 0 — Bridge spike (de-risk before architecture)

**Purpose:** prove the riskiest assumptions against *real Ansys* before writing
real architecture. Because a tutorial spans **three apps** (§2A) and per-app
verification access is **unknown**, the spike now covers all three. Spike code
lives in `spikes/`, is throwaway, and is allowed to be ugly. Each probe is a
standalone script with a clear pass/fail.

> Run the probes against the actual tutorial flow: open **Workbench**, then open
> **Discovery** from the Geometry cell, then **Mechanical** from the Model cell —
> probing each app as you reach it.

**Probe 0 — window discovery + transition detection (new, app lifecycle).**
From Python, detect the currently-running Ansys app windows by process name /
title. Then double-click the Geometry cell in Workbench and confirm you can
**detect Discovery's window appearing** within a few seconds (poll loop).
*Pass:* a script prints "workbench up", then after you trigger geometry, "discovery
appeared". This proves `wait_for_app()` is feasible — the core of transition steps.

**Probe 1 — model-state verification access, per app (this answers your "not sure").**
Find out what each app exposes to a Python script *from outside the app*:
- *Mechanical:* connect `ansys-mechanical-core` to the running session; list
  boundary conditions / mesh status. (Expected: works.)
- *Discovery:* check whether its scripting API is reachable externally, or only
  via the in-app scripting console. Record what's possible.
- *Workbench:* check whether `wbjn` journaling / project state is queryable live.
  (Expected: UIA-only for live checks.)
*Pass:* a written table of "for app X, I can verify a step via {scripting | UIA
only}". This single result reshapes the State verifier and is the most important
output of Phase 0.

**Probe 2 — UIA enumerates each app and returns bounding boxes.**
With pywinauto/uiautomation, walk the element tree of Workbench, then Discovery,
then Mechanical. For each, find a ribbon/toolbar button and a tree/schematic item;
print `name`, `automation_id`, screen `rectangle`.
*Pass:* a stable bounding box for at least one button + one tree item **in each
app**. *Watch for:* the 3D viewport showing as one opaque element in Discovery and
Mechanical (expected — see §2); note which apps expose `automation_id` vs name only.

**Probe 3 — pynput click + UIA "what was clicked", in the foreground app.**
Capture a real click via pynput; resolve which UIA element is at the click coords
**in whichever app is foreground**.
*Pass:* clicking a ribbon button or tree item yields the correct element name in
each app. *Expected limitation:* clicks inside a 3D viewport won't resolve — record
it; confirms geometry actions need model-state (script) verification, not UIA.

**Probe 4 — PyQt6 transparent click-through overlay (the High-severity one).**
Draw a glowing rectangle over a button using a transparent, frameless,
always-on-top PyQt6 window, and confirm it **re-anchors when you switch from one
Ansys app to another** (overlay must follow the foreground app). Then actually use
the app with the overlay up: clicks pass through the highlight to the app, but the
sidebar panel stays interactive.
*Pass:* you can click the highlighted button "through" the glow, click an overlay
sidebar button, and the overlay correctly retargets after an app switch.
*Technique:* per-region click-through on Windows via `WS_EX_TRANSPARENT` /
`WS_EX_LAYERED` (or a two-window split: a fully click-through highlight layer +
a separate interactive sidebar window). This is the spike's hardest part.

### Phase 0 exit gate (decision point)

Document results (screenshots / short screen recording + the per-app verification
table from Probe 1) for the deliverable. Then decide:

- **All pass →** proceed to Phase 1 with confidence; the architecture is sound.
- **Probe 0 fails** (can't detect app windows appearing) → fall back to a manual
  "I've opened it" confirmation button to advance transition steps; revisit later.
- **Probe 1 — per app:** wherever scripting works, use it for authoritative
  verification; wherever it doesn't (likely Workbench), the step uses a UIA
  `verify`. This is expected and handled by the per-step `verify.type` — not a
  failure, just a routing decision recorded in the schema.
- **Probe 2/3 partially fail** (UIA can't see parts of an app) → fall back to
  **image-template matching / OCR** for element location on those surfaces; keep
  UIA where it works. Adjust `selector.type` to allow `"image"`.
- **Probe 4 fails** (no clean click-through, or overlay won't retarget on app
  switch) → fall back to the two-window split, or a non-overlay docked side
  window. Changes the overlay design but not the rest.

---

## 6. Phase 1 — Vertical slice (one step, end to end)

Goal: one real step of "Apply Fixed Support" flows through **all three**
sub-components against real Ansys + the mock server.

1. Stand up the **mock FastAPI server** with the hand-authored tutorial JSON.
2. **Sync service v1:** `api_client` fetches the tutorial; `cache` stores it;
   `event_logger` writes events to SQLite. (Skip retry/backoff polish for now.)
3. **Runtime v1:** minimal `IDLE → LOADING → AWAITING_ACTION → VERIFYING →
   FINISHED` for a single step. Subscribe to bridge actions; use `verify_fast`
   for UIA steps and `verify_async` for `script` steps so the UI never blocks
   (eng-review decision 1). Guard against a stale async result arriving after the
   student already retried/cancelled the step (eng-review critical test).
4. **Bridge v1:** real `action_watcher` + `element_locator` + `state_verifier`,
   built directly on the proven spike code (now cleaned into the protocol).
5. **Overlay v1:** highlight the target element + a minimal step panel.
6. Wire in `app.py` with the correct threads (see §8).

**Exit:** student clicks the right element in Ansys, the app highlights it,
detects the click, verifies it, advances, and the event lands in SQLite. Demo it.

---

## 7. Phases 2–4 — fill out the architecture

**Phase 2 — Full Tutorial client.**
- Complete the 7-state machine incl. `STEP_FAILED` and `QUIZ`, with the two
  feedback loops back to `AWAITING_ACTION`.
- Overlay: progressive **hint balloon** on failure/request; full step panel
  (Show hint, Skip, Pause, Ask chatbot — button present, wired later).
- Highlight renderer tracks window movement via the element locator's
  event-driven re-query (window move/resize/foreground hooks + ~1-2 Hz safety
  poll), not a blind 10 Hz loop (eng-review decision 2).
- Add the `LAUNCHING` state for app-transition steps: long, configurable timeout
  (~120s), a "Waiting for {app} to open..." overlay, and a launch-failure path
  (eng-review decision 3).

**Phase 3 — Quiz + resilient Sync.**
- `quiz/runner.py`: multiple-choice, client-side grading, submit to mock server.
- Sync hardening: retry/backoff/timeout in `api_client`; background upload thread
  batching the SQLite buffer; **offline mode** — pull the tutorial from cache and
  buffer events to disk when the server is unreachable (the doc's "invisible
  outage" requirement). Test by killing the mock server mid-session.

**Phase 4 — Full tutorial + hardening.**
- Author the complete "Apply Fixed Support" tutorial (all steps + quiz).
- Multi-monitor / DPI testing (doc risk: DPI scaling — test one high-DPI monitor).
- Profile UIA load; confirm event-driven re-query keeps the highlight smooth
  under window moves; check the locator cache hit-rate.
- Graceful chatbot-unreachable message (button present, returns a clear notice).

---

## 8. Threading model (get this right early)

Per the doc, with two refinements from the engineering review:

- **Main thread:** PyQt6 event loop + **all** UI rendering + **all UIA queries**
  (COM thread affinity) — `verify_fast` and `locate` included.
- **Verification worker thread:** runs slow `script` checks (PyMechanical /
  Discovery; gRPC, not COM, so safe off-main). Result returns to the runtime via
  a Qt signal; the runtime sits in `VERIFYING` without blocking (decision 1).
- **Element locator:** no blind 10 Hz polling thread. The cached box refreshes on
  window move/resize/foreground-change events (Win32/UIA hooks, main thread) plus
  a ~1-2 Hz safety re-query (decision 2). Removes the main-thread UIA load behind
  the "UIA performance at 10 Hz" risk.
- **pynput listener thread:** receives OS input → pushes raw events onto a
  thread-safe queue the runtime drains.
- **Sync upload thread:** wakes periodically, flushes the SQLite event buffer.
- **(Later) chatbot query thread:** one per query so a slow LLM never blocks UI.

Cross-thread communication into Qt must use signals/slots or
`QMetaObject.invokeMethod`, never direct widget calls from worker threads.

---

## 9. Testing strategy

- **Client without Ansys:** `FakeBridge` emits scripted `SemanticAction`s and
  canned `VerificationResult`s; `FakeSync` serves a fixed tutorial. Drives the
  full state machine in CI with **no Ansys and no server**. This is the doc's
  "testable in isolation" promise made real.
- **State machine:** unit-test every transition incl. the two failure loops.
- **Sync resilience:** point `api_client` at a server that drops/500s; assert
  events buffer to SQLite and replay on recovery.
- **Bridge:** integration tests gated to a machine with Ansys (mark + skip in
  CI); manual probe scripts from Phase 0 become regression checks.
- **Per-app adapters:** unit-test each adapter's `locate` / `verify` /
  `identify_window` against a fake UIA tree / fake script layer (decision 4).
- **CRITICAL — async verify stale-result race:** a slow `verify_async` result
  arriving after the student retried or cancelled the step must be discarded,
  never applied to the wrong step. Unit-test with a controllable fake verifier.
- **CRITICAL — wrong-window routing race:** the bridge must target the expected
  app by window identity even when another Ansys app (or a dialog/splash) is
  foreground. Unit-test with a fake window table; assert no action routes to the
  wrong adapter.
- **LAUNCHING state:** test the timeout / launch-failure path with a fake
  `wait_for_app` that never resolves.

---

## 10. Module-specific risks (subset of doc §10 that this module owns)

| Risk | Severity | First place it's addressed |
|---|---|---|
| Per-region overlay click-through bugs | High | Phase 0 Probe 4 |
| Overlay must retarget across 3 apps on transition | High | Phase 0 Probe 4 (re-anchor) + Probe 0 |
| App-transition / window-appearance timing | Med | Phase 0 Probe 0; manual-confirm fallback |
| No model-state verification in some apps (e.g. Workbench) | Med | Per-step UIA `verify`; graceful degradation (§2A) |
| UIA can't see parts of an app (viewport) | Med-High | Phase 0 Probes 2-3 → image fallback |
| UIA performance under load | Med | Event-driven re-query + cache (decision 2); Phase 4 profiling |
| UI freeze on slow PyAnsys verify | Med | Async verify on worker thread (decision 1) |
| PyMechanical connection instability | Med | Auto-reconnect; treat as warning not fatal |
| DPI scaling on mixed monitors | Med | Phase 4 high-DPI test |
| Data loss on outage | Med | Phase 3 disk buffer + replay test |

---

## 11. The assignment (do this next, before any architecture code)

Since the tutorial **starts in Workbench**, probe that first, in a throwaway
`spikes/` folder:

1. `pip install ansys-mechanical-core pywinauto pynput pyqt6`
2. Open **Ansys Workbench** and create/load a project with a Static Structural
   system (so the Geometry and Model cells exist).
3. ~~`spikes/probe2_uia_workbench.py` (Probe 2)~~ -- **done, script removed.**
   Answer: UIA sees Workbench's ribbon/menu chrome but NOT the Toolbox or
   Project Schematic (zero descendants either way). See `mock_server/data/
   tut1.json`'s `_notes` for the full finding and `spikes/locate.py` for the
   OCR-based fallback (`locate_text`/`texts_found`) that resulted.
4. `spikes/probe0_transition.py` (Probe 0): detect the Workbench window, then
   double-click the Geometry cell yourself and confirm the script sees
   **Discovery's window appear**.
5. `spikes/probe1_pymechanical.py` (Probe 1): open Mechanical from the Model cell,
   attach `ansys-mechanical-core`, and print the boundary-condition list.

Those three answer the two biggest unknowns: *can the bridge see and target each
app* (Probes 2 + 0) and *what can we verify per app* (Probe 1, plus what you learn
about Discovery/Workbench scripting). If they work, the rest of this plan is
conventional Python. If any fights you, that's the most important thing to learn
now — almost always a config/launch-mode issue, not a dead end. Report back what
you see and we'll write the cleaned, app-aware bridge from there.

---

## Open questions to resolve as you go

- Does Mechanical 2025 R2 expose its gRPC server by default, or must it be
  launched a specific way for PyMechanical to attach? (Probe 1 answers this.)
- How much of the Ansys ribbon/tree carries stable `automation_id`s vs. only
  display names? (Probe 2 — prefer automation IDs for selector stability.)
- Single-window overlay with per-region transparency vs. two-window split?
  (Probe 4 decides.)
- Does Discovery expose its Python scripting API to an *external* process, or only
  via its in-app console? (Probe 1 — determines whether geometry steps get
  authoritative verification or fall back to UIA.)
- When a child app (Discovery/Mechanical) closes and focus returns to Workbench,
  how reliably can we detect the close + re-anchor the overlay? (Probe 0/4.)
- Does the full tutorial ever require *re-opening* Mechanical/Discovery after
  closing (re-attach), or is each opened exactly once? Affects bridge connection
  lifecycle.

---

## NOT in scope (considered, deferred)

- **Phases 2-4 detailed commitment** — hard-gated; re-review after the Phase 1 slice proves the assumptions.
- **Image-template matching / OCR fallback** — only built if Phase 0 Probes 2-3 show UIA can't see parts of an app.
- **Discovery authoritative verification** — falls back to UIA until Probe 1 confirms external scripting reachability.
- **Fluent track / multi-turn chatbot / adaptive recommendation** — system-level future work, not this module.
- **Child-app reconnect lifecycle** — open question; resolve once the real launch/close behavior is known.

## What already exists

Greenfield repo — nothing to reuse in-tree. The plan correctly reuses external infra
(PyMechanical, pywinauto/uiautomation, pynput, FastAPI, stdlib sqlite3) rather than
rebuilding. No unnecessary reinvention found.

## Failure modes (per new codepath)

| Codepath | Realistic failure | Test? | Error handling? | User sees |
|---|---|---|---|---|
| async verify | result returns after retry/cancel | yes (CRITICAL) | discard stale result | nothing wrong (correct) |
| app routing | wrong app foreground during action | yes (CRITICAL) | identity match | action ignored, not misrouted |
| LAUNCHING | child app never opens | yes | timeout → launch-failed | "couldn't open {app}" message |
| PyMechanical | gRPC disconnect mid-verify | Phase 3 | warning + reconnect | "checking..." then clear notice |
| Sync | server down mid-session | Phase 3 | disk buffer + replay | invisible (cached) |

No critical gaps (no failure that is silent AND untested AND unhandled).

## Parallelization

Sequential implementation. Phase 0 (spike) and Phase 1 (slice) are one workstream
on the bridge/runtime/overlay seam — no independent lanes worth splitting into worktrees yet.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues folded | 4 findings + 2 critical tests, all folded; scope hard-gated at Phase 1 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **VERDICT:** ENG review complete — 4 findings resolved into the plan (async verify, event-driven locator, LAUNCHING state + identity routing, per-app adapters) + 2 critical concurrency tests added. Outside voice not run (Codex not installed; Claude-subagent fallback offered, user's call). Ready to implement Phase 0 → Phase 1.

**UNRESOLVED DECISIONS:**
- Outside voice (independent plan challenge) not yet run — optional, non-blocking.

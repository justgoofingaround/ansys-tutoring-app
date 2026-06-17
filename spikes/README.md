# Phase 0 spike — throwaway probes

These scripts answer the riskiest questions in the build plan **before** we write
any real architecture. They are intentionally ugly and **not shipped**. See
`../Student-Track-App-Build-Plan.md` §5 for the full Phase 0 plan.

## Install

```
pip install pywinauto ansys-mechanical-core pynput pyqt6
```

## Run order (tutorial starts in Workbench)

Open **Ansys Workbench** with a project that has a Static Structural system
(so the Geometry and Model cells exist), then:

| Probe | Script | Question it answers | PASS looks like |
|---|---|---|---|
| 2 | `probe2_uia_workbench.py` | Can UIA see/locate Workbench elements? | prints name + rectangle for a Toolbox item and a schematic cell |
| 0 | `probe0_transition.py` | Can we detect a child app window appearing? | "Workbench up" → "discovery appeared after N s" once you open the Geometry cell |
| 1 | `probe1_pymechanical.py` | Can we read model state from Mechanical? | prints the analyses/boundary-conditions of your open model |

Then come back with what you saw — especially:
- which Workbench elements had a non-empty `automation_id` (preferred for selectors),
- how long the child app took to appear,
- whether Path A in probe 1 connected, and if not, what it took to enable gRPC.

That output is what we turn into the cleaned, app-aware `bridge/` (with the
per-app adapters and async verify from the engineering review).

## Notes / things you'll likely tweak

- **Window titles** (`TITLE_HINT`, `APP_TITLES`) are guesses — adjust to whatever
  the real windows report.
- **probe 1 port** (`PORT = 10000`) may differ; a GUI Mechanical only exposes gRPC
  if its remote server is enabled — discovering how is part of the probe.
- All probes are **read-only**; none modify your Ansys model.
- Not added to `requirements.txt` on purpose — these deps are spike-only until the
  real module pins them.

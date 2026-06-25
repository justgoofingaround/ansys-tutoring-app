# Ansys Tutoring System — ME-UY 4214

An AI-assisted overlay that guides students step-by-step through Ansys tutorials, live, on top of the real application.

![Guided overlay running on top of Ansys Workbench](app.png)

Built for NYU's ME-UY 4214 (Finite Element Analysis lab) as part of an AI in Education Seed Grant, with a pilot planned for Fall 2026. A transparent, click-through panel sits on top of Ansys Workbench and Mechanical, highlighting exactly which element to interact with next and walking the student through the tutorial step by step — including the multi-app handoff every tutorial requires: Workbench → Discovery/SpaceClaim (geometry) → back to Workbench → Mechanical (FEA/solve). Each step is confirmed by the student via a "Mark step complete" button rather than automatic detection — see [`spikes/guide_tut1.py`](spikes/guide_tut1.py)'s module docstring for why.

The system is local-first by design: no student interaction data leaves NYU infrastructure, and no cloud LLM ever touches student data.

See [`Student-Track-App-Build-Plan.md`](Student-Track-App-Build-Plan.md) for the build plan and [`CLAUDE.md`](CLAUDE.md) for project conventions and architecture pointers.

## Status

This is the Phase 0 spike (`spikes/guide_tut1.py`) — a working, manually-driven walkthrough of part of Tut-1, used to de-risk the real architecture's assumptions before it gets built for real under `student_app/`. It currently covers Workbench setup through Mechanical's results steps (see `STEP_IDS` in `guide_tut1.py`); SpaceClaim and Engineering Data sections of Tut-1 exist in the tutorial data but aren't wired into this spike's run yet.

## How to use it

1. **Install dependencies** (Python 3.11+, Windows):
   ```
   pip install pywinauto pyqt6 opencv-python-headless numpy pillow pytesseract
   ```
   You'll also need the [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) binary installed system-wide (used to read on-screen text Ansys doesn't expose via UI Automation), plus an English language file at `spikes/tessdata/eng.traineddata` — see that folder if it's missing.

2. **Open Ansys Workbench** (2025 R2) — either have it already open, or be ready to open it as soon as the guide starts, since step 1 walks you through launching it.

3. **Run the guide**:
   ```
   .venv\Scripts\python spikes\guide_tut1.py
   ```
   A dark panel appears in the top-right corner of your screen, on top of Ansys.

4. **Follow each step:**
   - Read the instruction and hint text in the panel.
   - If a red box appears on screen, that's the live-highlighted element for this step — wherever the box is, that's what to click/interact with next.
   - Some steps (e.g. picking a 3D face in the geometry viewport) show a reference screenshot instead of a live box, since there's nothing to highlight via automation there.
   - Perform the action in the real Ansys window.
   - Click **"✓ Mark step complete"** once you've done it, then **"Next →"** to advance. Use **"← Prev"** to go back.

5. The guide walks you all the way from opening Workbench through generating and saving the final FEA result in Mechanical.

**Note:** the guide is the only thing you run directly — `mock_server/` (a FastAPI stand-in for the real Tutorials & Quizzes server) isn't needed for this spike; `guide_tut1.py` reads `mock_server/data/tut1.json` straight off disk.

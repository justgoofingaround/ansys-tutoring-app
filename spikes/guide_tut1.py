"""
Guided overlay for Tut-1 — built one step at a time.

CODE ORGANIZATION (three modules, each owning one concern):
  - guide_tut1.py (this file) -- the UI/panel: what the student sees, how
    they navigate, when to draw a highlight box. Owns no verification or
    element-finding logic itself.
  - verify.py -- "is this step done?" Dispatches on a step's verify.type.
  - locate.py -- "where is this element on screen, if anywhere?" Dispatches
    on a step's selector/action fields, drives the live UIA query.
This mirrors the real architecture's split between the Tutorial client and
the Ansys bridge's State verifier / Element locator sub-pieces (CLAUDE.md).

VERIFICATION IS MANUAL FOR EVERY STEP, ON PURPOSE: automatic checks
(window_appeared, window_title_excludes, ocr_text_present, row_status_icon,
and a PyMechanical gRPC integration) were built and DID work, but were
deliberately removed -- continuing to chase OCR/UIA/gRPC reliability issues
wasn't worth the fragility for a student-facing pilot. See tut1.json's
_notes.manual_verify_switch_2026-06 for the full reasoning. Every step's
verify.type is now "manual" (or an unimplemented "uia"/"script" type that
falls through to the same manual-confirm path in verify.py) -- the student
clicks "Mark step complete" once they've actually done the action.

HIGHLIGHTING IS UNCHANGED -- the live box is independent of how a step gets
verified, so all of this is still accurate:
  - highlight: "none" (step 1) -- no box, process-launch step.
  - highlight: "uia" (most steps) -- ElementLocator finds a named element in
    the live UIA tree. Workbench's ribbon/menu chrome IS UIA-visible;
    Mechanical's Outline tree/Details panel are WPF and expected to be too
    (live-tested this session). Multi-stage actions (e.g. step 2's File ->
    Save As, or right_click -> menu_select sequences) box ONLY the outer/
    topmost name via target_sequence() -- transient popup rows don't expose
    a stable per-item name, so the rest is left to the step's hint text.
  - highlight: "ocr_text" (steps 3-5) -- Workbench's Toolbox panel and
    Project Schematic canvas have ZERO UIA or win32 HWND accessibility
    (confirmed via diagnostic probes since removed, see tut1.json _notes).
    locate.locate_text() reads the live text via pytesseract OCR instead;
    image-template matching was tried first and rejected (matched the wrong
    row). selector.scope=="schematic" scopes the search to
    locate.schematic_rect() instead of the Toolbox; extend_to_icon=True
    (steps 4-5) widens the box to also enclose the row's status icon.
  - highlight: "instruction" (steps 12, 15) -- picking a 3D face in the
    geometry viewport isn't a UIA element at all, so these show the
    tutorial's reference screenshot via _load_reference_image() instead of a
    live box.

STEP 6 ONWARD note: load_steps() now takes an explicit step_id list
(STEP_IDS, near main()), not a prefix count -- tut1.json's section order
follows the original tutorial doc (Workbench -> SpaceClaim -> Engineering
Data -> Mechanical), but live testing jumped straight from Workbench to
Mechanical, skipping SpaceClaim/Engineering Data. ALSO: Panel now owns one
ElementLocator PER APP (self._locators, created lazily via _locator_for()),
not a single hardcoded "workbench" locator, since steps 6-8 are the first to
target a different app.

RUN (with Workbench already open, or about to open it):
  .venv\\Scripts\\python spikes\\guide_tut1.py

DEPS: pip install pywinauto pyqt6 opencv-python-headless numpy pillow pytesseract
      (psutil/ansys-mechanical-core no longer needed by the live guide --
      only the standalone probe0/probe1 scripts still use them)
"""

import json
import os
import sys
from pathlib import Path

# Disable Qt auto-DPI scaling so widget geometry matches UIA's physical
# pixels (needed now that step 2 actually draws a box).
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

import locate
import verify

REPO_ROOT = Path(__file__).resolve().parents[1]
TUT_PATH = REPO_ROOT / "mock_server" / "data" / "tut1.json"
RELOCATE_MS = 700   # re-check ~1.4 Hz: follows window moves AND advances the
                     # highlight stage quickly once a menu opens
OCR_MISS_TOLERANCE = 6  # consecutive OCR misses (each already internally
                         # retried in locate.locate_text()) to tolerate before
                         # hiding the ocr_text box -- absorbs flicker
DEBUG = True         # print diagnostic lines to the console


def load_steps(step_ids):
    """Load tut1.json's steps by explicit step_id, in `step_ids`' order --
    NOT a prefix slice of the document. tut1.json's section order follows the
    ORIGINAL tutorial doc (Workbench -> SpaceClaim -> Engineering Data ->
    Mechanical), which is the authoritative structure for real use later --
    but this spike's live testing has jumped straight from Workbench to
    Mechanical (skipping SpaceClaim/Engineering Data for now), so a strict
    "first N steps" slice would load the wrong section entirely. Keeping
    tut1.json's own ordering untouched and selecting explicitly here keeps
    today's testing order decoupled from the canonical tutorial structure."""
    data = json.loads(TUT_PATH.read_text(encoding="utf-8"))
    by_id = {}
    for sec in data["sections"]:
        for st in sec["steps"]:
            st["_section"] = sec["section"]
            by_id[st["step_id"]] = st
    return [by_id[sid] for sid in step_ids]


class Highlight(QtWidgets.QWidget):
    """Click-through, always-on-top red outline around the target element."""

    def __init__(self):
        flags = (QtCore.Qt.WindowType.FramelessWindowHint
                 | QtCore.Qt.WindowType.WindowStaysOnTopHint
                 | QtCore.Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setWindowTitle("__TutGuideHighlight__")  # never a real selector target
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._has_box = False

    def show_box(self, rect):
        self._has_box = rect is not None
        if rect:
            l, t, r, b = rect
            # UIA returns PHYSICAL pixels; Qt6 always scales widget geometry
            # to logical pixels, so we convert or the box lands off-screen.
            screen = QtWidgets.QApplication.primaryScreen()
            dpr = screen.devicePixelRatio() if screen else 1.0
            if dpr and dpr != 1.0:
                l, t, r, b = l / dpr, t / dpr, r / dpr, b / dpr
            pad = 6
            self.setGeometry(int(l - pad), int(t - pad), int((r - l) + 2 * pad), int((b - t) + 2 * pad))
            self.show()
            self.raise_()
            self.update()
        else:
            self.hide()

    def paintEvent(self, _):
        if not self._has_box:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 40, 40), 3))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 6, 6)


class Panel(QtWidgets.QWidget):
    """Step panel. Calls verify.verify_step() / locate.* and reacts -- never
    implements verification or element-finding itself."""

    def __init__(self, steps):
        flags = (QtCore.Qt.WindowType.FramelessWindowHint
                 | QtCore.Qt.WindowType.WindowStaysOnTopHint
                 | QtCore.Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setWindowTitle("__TutGuidePanel__")  # never a real selector target
        self.steps = steps
        self.i = 0
        self.manually_confirmed = False
        # One ElementLocator per app, created lazily as steps need different
        # apps (locate.py's documented design) -- steps 6-8 are the first to
        # need "mechanical" rather than "workbench".
        self._locators = {}
        # OCR is noisy frame-to-frame (slight render/hinting differences cause
        # an occasional single-tick miss even while the row is fully visible
        # and unchanged) -- without this, the box visibly flickers off and
        # back on every couple of ticks. Tolerate a few consecutive misses
        # before actually hiding the box; a real scroll-away still hides it,
        # just a tick or two later.
        self._ocr_last_rect = None
        self._ocr_miss_streak = 0
        self.highlight = Highlight()

        self.setFixedWidth(380)
        self.setStyleSheet("background:#1e1e1e;color:#eee;border-radius:8px;")
        v = QtWidgets.QVBoxLayout(self)
        self.lbl_prog = QtWidgets.QLabel()
        self.lbl_prog.setStyleSheet("color:#9cf;font-size:11px;")
        self.lbl_title = QtWidgets.QLabel()
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet("font-size:15px;font-weight:bold;")
        self.lbl_desc = QtWidgets.QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_hint = QtWidgets.QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#bbb;font-size:12px;font-style:italic;")
        # Reference screenshot for highlight=="instruction" steps -- UIA can't
        # box these (e.g. Workbench's Toolbox/Schematic are UIA-blind, see
        # tut1.json _notes), so a static image stands in for a live box.
        self.lbl_image = QtWidgets.QLabel()
        self.lbl_image.setVisible(False)
        self.lbl_status = QtWidgets.QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:12px;")
        for w in (self.lbl_prog, self.lbl_title, self.lbl_desc, self.lbl_hint, self.lbl_image, self.lbl_status):
            v.addWidget(w)

        row = QtWidgets.QHBoxLayout()
        self.btn_prev = QtWidgets.QPushButton("← Prev")
        self.btn_next = QtWidgets.QPushButton("Next →")
        for b in (self.btn_prev, self.btn_next):
            row.addWidget(b)
        v.addLayout(row)
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_next.clicked.connect(lambda: self.go(1))

        self.btn_mark = QtWidgets.QPushButton("✓ Mark step complete")
        self.btn_mark.setVisible(False)
        self.btn_mark.clicked.connect(self.mark_complete)
        v.addWidget(self.btn_mark)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(RELOCATE_MS)

        self._place_top_right()
        self.render_step()

    def _place_top_right(self):
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(scr.right() - self.width() - 24, scr.top() + 24)

    def _current(self):
        return self.steps[self.i]

    def _locator_for(self, app_key):
        if app_key not in self._locators:
            self._locators[app_key] = locate.ElementLocator(app_key)
        return self._locators[app_key]

    def go(self, delta):
        self.i = max(0, min(len(self.steps) - 1, self.i + delta))
        self.render_step()

    def mark_complete(self):
        self.manually_confirmed = True
        self._tick()

    def render_step(self):
        st = self._current()
        self.manually_confirmed = False
        self._ocr_last_rect = None
        self._ocr_miss_streak = 0
        self.lbl_prog.setText(f"Step {self.i + 1}/{len(self.steps)}  ·  {st['_section']}")
        self.lbl_title.setText(st["title"])
        self.lbl_desc.setText(st["description"])
        hints = st.get("hints") or []
        self.lbl_hint.setText(("Hint: " + hints[0]) if hints else "")
        self.btn_prev.setEnabled(self.i > 0)
        self._load_reference_image(st)
        self._tick()
        self._place_top_right()

    def _load_reference_image(self, st):
        # Only for highlight=="instruction" steps -- once a live box exists
        # (highlight=="uia" or "ocr_text"), the box itself is the guidance.
        img_path = st.get("source_image") if st.get("highlight") == "instruction" else None
        pix = QtGui.QPixmap(str(REPO_ROOT / img_path)) if img_path else None
        if pix and not pix.isNull():
            self.lbl_image.setPixmap(pix.scaledToWidth(
                340, QtCore.Qt.TransformationMode.SmoothTransformation))
            self.lbl_image.setVisible(True)
        else:
            if img_path and DEBUG:
                print(f"[debug] reference image not loadable: {REPO_ROOT / img_path}")
            self.lbl_image.setVisible(False)

    def _own_screen_rect(self):
        """This panel's own rect in PHYSICAL screen pixels (Qt's geometry()
        is logical pixels -- same dpr conversion as Highlight.show_box, just
        inverted). Passed to locate.set_exclude_rects() so OCR/color-sampling
        never reads this panel's own status text -- confirmed live: once
        Workbench's window is large enough that a capture region (e.g. the
        schematic) overlaps this floating panel's screen position, OCR read
        the PANEL'S OWN text ("highlighting 'Geometry'", "Not yet — finish
        the action above.", "Prev") mixed into the real content underneath.
        Deliberately excludes self.highlight -- that box is drawn ON TOP OF
        the real target on purpose and must stay visible to OCR."""
        screen = QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        g = self.geometry()
        rect = (g.left() * dpr, g.top() * dpr, (g.left() + g.width()) * dpr, (g.top() + g.height()) * dpr)
        if DEBUG:
            print(f"[debug] _own_screen_rect: logical geometry={g} dpr={dpr} -> physical rect={rect}")
        return rect

    def _tick(self):
        st = self._current()
        locate.set_exclude_rects([self._own_screen_rect()])

        # --- highlighting ---
        # Box ONLY the outer/topmost element of the sequence (e.g. "File").
        # Workbench's native dropdown items don't expose a stable per-row
        # name once open -- matching flipped between "found (wrong size)"
        # and "not found at all" depending on mouse position, so trying to
        # live-box anything INSIDE a transient popup is a dead end here.
        # Remaining stages are left to the step's existing description/hints
        # text instead of an attempted box.
        if st.get("highlight") == "uia":
            locator = self._locator_for(st["app"])
            locator.refresh_snapshot()
            seq = locate.target_sequence(st)
            target = seq[0] if seq else None
            rect = locator.locate(target) if target else None
            self.highlight.show_box(rect)
            if not rect:
                located_txt = f"⚠ couldn't find '{target}' — selector needs tuning." if target else ""
            elif len(seq) > 1:
                located_txt = f"✓ highlighting '{target}' — then: {', '.join(seq[1:])}"
            else:
                located_txt = f"✓ highlighting '{target}'"
        elif st.get("highlight") == "ocr_text":
            # No UIA or win32 accessibility exists for Toolbox rows at all
            # (confirmed via diagnostic probes since removed -- see tut1.json
            # _notes). Image-template matching was tried and rejected (it locked onto
            # "Modal" instead of "Static Structural" -- rows share the same
            # icon+text layout, so pixel correlation doesn't discriminate
            # them). OCR reads the actual text instead.
            sel = st.get("selector", {})
            text = sel.get("text") or sel.get("name")
            # Same OCR text-finder as the Toolbox case, but scoped to the
            # schematic canvas instead when the step says so (e.g. step 4's
            # "Geometry" lives in the schematic's system block, not the
            # Toolbox -- locate_text()'s default region is the Toolbox rect).
            # extend_to_icon=True for schematic rows so the box also encloses
            # the row's status icon (checkmark/question-mark), not just the
            # label text -- Toolbox rows have no such icon to extend toward.
            is_schematic = sel.get("scope") == "schematic"
            region = locate.schematic_rect() if is_schematic else None
            rect = locate.locate_text(text, region_rect=region, extend_to_icon=is_schematic) if text else None
            if rect is not None:
                self._ocr_last_rect = rect
                self._ocr_miss_streak = 0
            elif self._ocr_last_rect is not None:
                self._ocr_miss_streak += 1
                if self._ocr_miss_streak <= OCR_MISS_TOLERANCE:
                    rect = self._ocr_last_rect  # ride out a brief OCR miss with the last good box
                else:
                    self._ocr_last_rect = None
            self.highlight.show_box(rect)
            located_txt = (
                f"✓ highlighting '{text}'" if rect else
                f"⚠ couldn't find '{text}' on screen — is it scrolled into view?"
            )
        else:
            self.highlight.show_box(None)
            located_txt = ""

        # --- verification ---
        verified = verify.verify_step(st)
        if DEBUG:
            print(f"[debug] step {self.i + 1}/{len(self.steps)} '{st['step_id']}' "
                  f"verify_step() -> {verified}")
        if verified is True:
            status, next_ok, color = "Verified — step complete.", True, "#7e7"
        elif verified is False:
            status, next_ok, color = "Not yet — finish the action above.", False, "#fb7"
        else:
            status = "Once this step is complete, please mark it as done and then move on to the next."
            next_ok = self.manually_confirmed
            color = "#7e7" if self.manually_confirmed else "#9cf"

        self.lbl_status.setText((located_txt + "\n" if located_txt else "") + status)
        self.lbl_status.setStyleSheet(f"color:{color};font-size:12px;")
        self.btn_next.setEnabled(next_ok and self.i < len(self.steps) - 1)
        # Based on the ACTUAL runtime result, not a static guess from
        # verify.type -- a hardcoded `type in ("manual", "script")` check
        # here once missed verify.type=="uia" (and would miss any future
        # type) whenever it returns None because that check just isn't
        # implemented yet, leaving no way to advance past the step at all.
        self.btn_mark.setVisible(verified is None)
        self.btn_mark.setEnabled(not self.manually_confirmed)

    def closeEvent(self, e):
        self.highlight.close()
        super().closeEvent(e)


STEP_IDS = [
    "wb_01_open", "wb_02_save_project", "wb_03_add_static_structural",
    "wb_04_select_geometry", "wb_05_select_model",
    "me_01_expand_geometry", "me_02_select_solid", "me_03_set_material_steel",
    "me_04_generate_mesh",
    "me_05_select_static", "me_06_force_tool", "me_07_force_face",
    "me_08_force_magnitude", "me_09_fixed_tool", "me_10_fixed_face",
    "re_01_insert_dir_deformation", "re_02_orientation", "re_03_evaluate",
    "me_11_solve",
    "re_04_save",
]


def main():
    if not TUT_PATH.exists():
        sys.exit(f"tutorial not found: {TUT_PATH}")
    steps = load_steps(STEP_IDS)

    qapp = QtWidgets.QApplication(sys.argv)
    panel = Panel(steps)
    panel.show()
    print(f"Guiding {len(steps)} step(s). Make sure Ansys Workbench is open.")
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()

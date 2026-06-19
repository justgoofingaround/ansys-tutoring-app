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

STEPS BUILT SO FAR (from Tut 1, "Create a new Static Structural analysis case"):
  1. "Open Ansys Workbench 2020 R2"      -- highlight: none, verify: process check
  2. "Save the project as Tut-1"         -- highlight: uia, boxes "File" only
                                             (Workbench's dropdown rows have no
                                             stable per-item name once open --
                                             "Save As..." is left to the step's
                                             text, not a live box),
                                             verify: window_title_excludes
                                             ("Unsaved Project" leaves the
                                             title bar once actually saved)
  3. "Add a Static Structural analysis"  -- highlight: ocr_text (Toolbox rows
                                             have ZERO UIA or win32 HWND
                                             accessibility, confirmed via
                                             diagnostic probes since removed
                                             (tut1.json _notes); image-template
                                             matching was tried and rejected --
                                             it matched the wrong row since all
                                             rows share the same icon+text
                                             layout -- so this reads the live
                                             Toolbox text via pytesseract OCR
                                             and boxes whichever line says
                                             "Static Structural"),
                                             verify: ocr_text_present, checks
                                             every row label of the schematic
                                             system block (Engineering Data /
                                             Geometry / Model / Setup /
                                             Solution / Results) is present --
                                             "Static Structural" itself is
                                             excluded since it's also the
                                             Toolbox's own permanent row
  4. "Select Geometry"                   -- highlight: ocr_text, same OCR
                                             machinery as step 3 but scoped to
                                             locate.schematic_rect() instead of
                                             the Toolbox (selector.scope ==
                                             "schematic") -- boxes the
                                             "Geometry" row inside the
                                             schematic's Static Structural
                                             block, verify: window_appeared
                                             ("spaceclaim" process check, same
                                             pattern as step 1)

RUN (with Workbench already open, or about to open it):
  .venv\\Scripts\\python spikes\\guide_tut1.py

DEPS: pip install psutil pywinauto pyqt6
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


def load_steps(upto):
    """Flatten tut1.json's sections into one ordered list, sliced to the
    first `upto` steps -- single source of truth for tutorial content, even
    though we only use a prefix of it right now."""
    data = json.loads(TUT_PATH.read_text(encoding="utf-8"))
    steps = []
    for sec in data["sections"]:
        for st in sec["steps"]:
            st["_section"] = sec["section"]
            steps.append(st)
            if len(steps) >= upto:
                return steps
    return steps


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
        self.element_locator = locate.ElementLocator("workbench")
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
        self.btn_mark.setVisible(st.get("verify", {}).get("type") in ("manual", "script"))
        self._load_reference_image(st)
        self._tick()
        self._place_top_right()

    def _load_reference_image(self, st):
        # Only for highlight=="instruction" steps -- once a live box exists
        # (highlight=="uia" or "template"), the box itself is the guidance.
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

    def _tick(self):
        st = self._current()

        # --- highlighting ---
        # Box ONLY the outer/topmost element of the sequence (e.g. "File").
        # Workbench's native dropdown items don't expose a stable per-row
        # name once open -- matching flipped between "found (wrong size)"
        # and "not found at all" depending on mouse position, so trying to
        # live-box anything INSIDE a transient popup is a dead end here.
        # Remaining stages are left to the step's existing description/hints
        # text instead of an attempted box.
        if st.get("highlight") == "uia":
            self.element_locator.refresh_snapshot()
            seq = locate.target_sequence(st)
            target = seq[0] if seq else None
            rect = self.element_locator.locate(target) if target else None
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
            region = locate.schematic_rect() if sel.get("scope") == "schematic" else None
            rect = locate.locate_text(text, region_rect=region) if text else None
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
            status = "No automatic check for this step — confirm manually below."
            next_ok = self.manually_confirmed
            color = "#7e7" if self.manually_confirmed else "#9cf"

        self.lbl_status.setText((located_txt + "\n" if located_txt else "") + status)
        self.lbl_status.setStyleSheet(f"color:{color};font-size:12px;")
        self.btn_next.setEnabled(next_ok and self.i < len(self.steps) - 1)
        self.btn_mark.setEnabled(not self.manually_confirmed)

    def closeEvent(self, e):
        self.highlight.close()
        super().closeEvent(e)


def main():
    if not TUT_PATH.exists():
        sys.exit(f"tutorial not found: {TUT_PATH}")
    steps = load_steps(upto=4)

    qapp = QtWidgets.QApplication(sys.argv)
    panel = Panel(steps)
    panel.show()
    print(f"Guiding {len(steps)} step(s). Make sure Ansys Workbench is open.")
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()

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

"ASK CHATBOT" BUTTON: bridges to chatbot_spike/ (a SEPARATE module's spike --
see chatbot_spike/README.md and architecture doc Section 8, "Module: Ansys
Help Chatbot") via the CHATBOT_DIR sys.path insert below, rather than
duplicating its retrieve/generate pipeline here. ChatbotDialog is non-modal
and ChatbotWorker runs on a background QThread, since a real query (local
LLM generation) takes several seconds and the main thread must never block
(CLAUDE.md's threading rule). tutorial_context is set to the current step's
title -- a stand-in for the architecture doc's "Context fetcher" sub-
component, which in the real module queries the Student Track App's state
automatically instead of guide_tut1.py setting it directly on itself.
ChatbotDialog's UI is modeled on a user-supplied Figma reference (light
theme, gradient background, "ME"/"OUR AI" captioned bubbles, pill-shaped
input). Each message turn is a REAL MessageBubble (QFrame) widget in a
QScrollArea, not text appended into one shared QTextEdit document -- true
border-radius (the reference's rounded bubbles) isn't reliably supported on
inline/table elements in Qt's rich-text engine, confirmed across this
dialog's earlier iterations, but works fine via stylesheet on a real QFrame.

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

TUTORIALS ARE JSON-DRIVEN: the guide takes any tutorial JSON as its input --
no per-tutorial code. Which steps run (and in what order) comes from the
JSON's optional top-level "runtime_steps" list of step_ids; without it, every
step runs in document order. tut1.json uses runtime_steps for ORDERING: the
result-insertion steps (re_01..re_03) run before me_11_solve so one solve
evaluates them, which document order can't express without breaking the
section grouping. The synthetic report-upload step is appended only when the
tutorial declares a "report_checks" rubric. Panel owns one ElementLocator
PER APP (self._locators, created lazily via _locator_for()), since a
tutorial spans multiple apps.

RUN (with Workbench already open, or about to open it):
  .venv\\Scripts\\python spikes\\guide_tut1.py                     # defaults to tut1.json
  .venv\\Scripts\\python spikes\\guide_tut1.py mock_server\\data\\tut2.json
  .venv\\Scripts\\python spikes\\guide_tut1.py tut2                # bare id -> mock_server/data/tut2.json

DEPS: pip install pywinauto pyqt6 opencv-python-headless numpy pillow pytesseract markdown
      (markdown renders the chatbot's answers; the chatbot feature itself also
      needs chatbot_spike/'s own deps -- see chatbot_spike/requirements.txt --
      but guide_tut1.py still runs fine without them, just with the chatbot
      button showing a graceful error instead, see ChatbotDialog._on_failed)
      (psutil/ansys-mechanical-core no longer needed by the live guide --
      only the standalone probe0/probe1 scripts still use them)
"""

import json
import os
import sys
import time
from pathlib import Path

# Disable Qt auto-DPI scaling so widget geometry matches UIA's physical
# pixels (needed now that step 2 actually draws a box).
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

import locate
import report_verify
import verify

REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIALS_DIR = REPO_ROOT / "mock_server" / "data"
DEFAULT_TUT_PATH = TUTORIALS_DIR / "tut1.json"
# The web app's "Close guide" button (ansysguide://close -> guide_launcher.py)
# can't reach this process directly, so it drops this sentinel file instead;
# Panel._tick() polls for it. Must match STOP_FILE in tools/guide_launcher.py.
STOP_FILE = REPO_ROOT / "server_data" / "guide_stop"


def resolve_tutorial_path(arg):
    """Turn the CLI argument into a tutorial JSON path. Accepts a real path
    (absolute, or relative to the cwd or repo root), a bare file name
    ('tut2' -> mock_server/data/tut2.json), or a tutorial_id from inside any
    JSON in mock_server/data ('tut1_3d_bar' -> tut1.json)."""
    if not arg:
        return DEFAULT_TUT_PATH
    for candidate in (Path(arg), REPO_ROOT / arg,
                      TUTORIALS_DIR / arg, TUTORIALS_DIR / f"{arg}.json"):
        if candidate.is_file():
            return candidate.resolve()
    for candidate in sorted(TUTORIALS_DIR.glob("*.json")):
        if candidate.name.startswith("_"):
            continue  # templates aren't runnable tutorials
        try:
            if json.loads(candidate.read_text(encoding="utf-8")).get("tutorial_id") == arg:
                return candidate.resolve()
        except (OSError, json.JSONDecodeError):
            continue
    return Path(arg)  # let main() report the miss with the name as given

# chatbot_spike/ is a SEPARATE module (architecture doc Section 8, its own
# spike directory -- see chatbot_spike/README.md), not part of the Student
# Interaction Track App's spike. Its modules use bare imports (`from config
# import ...`) that resolve relative to chatbot_spike/ being on sys.path,
# the same convention this file's own `import locate`/`import verify` relies
# on for spikes/. Bridging it here is the simplest way to call the already-
# working retrieve/generate pipeline in-process (one model load per running
# guide_tut1.py session) instead of shelling out to query.py per question,
# which would reload the embedding model from scratch every single ask.
CHATBOT_DIR = REPO_ROOT / "chatbot_spike"
if CHATBOT_DIR.exists() and str(CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(CHATBOT_DIR))
RELOCATE_MS = 700   # re-check ~1.4 Hz: follows window moves AND advances the
                     # highlight stage quickly once a menu opens
OCR_MISS_TOLERANCE = 6  # consecutive OCR misses (each already internally
                         # retried in locate.locate_text()) to tolerate before
                         # hiding the ocr_text box -- absorbs flicker
DEBUG = True         # print diagnostic lines to the console


def load_steps(data):
    """Flatten a tutorial dict's sections into the runtime step list.

    Which steps run, and in what order, is the JSON's decision, not code's:
    the optional top-level "runtime_steps" list of step_ids selects/orders
    steps explicitly; without it, every step runs in document order. tut1.json
    uses it to run re_01..re_03 (insert results) BEFORE me_11_solve so a
    single solve evaluates them -- an order the section grouping can't
    express."""
    by_id = {}
    ordered = []
    for sec in data["sections"]:
        for st in sec["steps"]:
            st["_section"] = sec["section"]
            by_id[st["step_id"]] = st
            ordered.append(st)
    step_ids = data.get("runtime_steps")
    if not step_ids:
        return ordered
    missing = [sid for sid in step_ids if sid not in by_id]
    if missing:
        sys.exit(f"runtime_steps references step_id(s) not in the tutorial: {missing}")
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


class ChatbotWorker(QtCore.QObject):
    """Runs chatbot_spike's retrieve+generate pipeline OFF the Qt main
    thread -- a real query takes several seconds (embedding + ChromaDB/BM25
    search + a local Ollama generation call), and CLAUDE.md/the build plan
    are explicit that the main thread owns the event loop and must never
    block on slow work. Imports chatbot_spike's modules lazily, inside run(),
    so a missing/broken chatbot install only breaks the chatbot feature, not
    guide_tut1.py's own startup.

    Streams tokens (the `token` signal) rather than waiting for the full
    answer -- confirmed live, an unbounded answer took a long time to fully
    generate, and watching nothing happen for that whole stretch made the
    chatbot feel far slower than it was. Streaming doesn't reduce the actual
    generation time, but the student sees the answer growing immediately
    instead of a frozen "Thinking..." -- the standard chat-UI fix for
    exactly this perceived-latency problem. Actual latency is separately
    addressed by config.MAX_RESPONSE_TOKENS (chatbot_spike/generate.py)
    capping how much the model generates in the first place."""
    token = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(str, list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, question, tutorial_context):
        super().__init__()
        self.question = question
        self.tutorial_context = tutorial_context

    def run(self):
        try:
            from retrieve import retrieve
            from generate import stream_answer
            chunks = retrieve(self.question)
            answer, sources = stream_answer(
                self.question, chunks, tutorial_context=self.tutorial_context,
                on_token=self.token.emit)
            self.finished.emit(answer, sources)
        except Exception as e:
            if DEBUG:
                print(f"[debug] ChatbotWorker failed: {e}")
            self.failed.emit(str(e))


class MessageBubble(QtWidgets.QFrame):
    """One chat turn's bubble -- a REAL QFrame/QLabel widget, not rendered
    rich text inside a shared QTextEdit document. True border-radius (the
    Figma reference's rounded message bubbles) isn't reliably supported on
    inline/table elements in Qt's rich-text engine (confirmed live across
    this dialog's earlier iterations), but IS fully supported via stylesheet
    on a real QFrame -- so each message turn now gets its own bubble widget
    in a QVBoxLayout/QScrollArea instead of being appended into one document."""

    def __init__(self, caption, bg, text_color, border=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background:{bg}; border-radius:14px; "
            f"{f'border:1px solid {border};' if border else ''} }}")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(16, 10, 16, 12)
        v.setSpacing(4)
        self.caption = QtWidgets.QLabel(caption)
        self.caption.setStyleSheet(
            f"background:transparent; color:#9a96a8; font-size:11px; "
            f"font-weight:600; letter-spacing:1px;")
        v.addWidget(self.caption)
        self.body = QtWidgets.QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.body.setStyleSheet(f"background:transparent; color:{text_color}; font-size:15px;")
        v.addWidget(self.body)
        self._raw = ""  # accumulates plain streamed text until set_html() takes over

    def append_token(self, piece):
        self._raw += piece
        self.body.setText(self._escape(self._raw))

    def set_html(self, html):
        self.body.setText(html)

    @staticmethod
    def _escape(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ChatbotDialog(QtWidgets.QDialog):
    """Non-modal (.show(), never .exec()) so asking the chatbot never
    freezes the live highlight loop running in the Panel underneath it.
    "Graceful chatbot-unreachable message (button present, returns a clear
    notice)" is a Phase 4 requirement already named in the build plan --
    _on_failed() below is exactly that, just arriving earlier than planned
    since the chatbot spike already exists to wire up.

    Layout modeled on a Figma "AI Chatbot UI" reference the user shared:
    sparkle header, soft pastel gradient page background, "ME"/"OUR AI"
    captioned bubbles staggered left-to-right, a pill-shaped input with an
    embedded send icon, and suggestion chips shown before the first message."""

    ERROR_COLOR = "#c0392b"
    USER_BG = "#fbeef6"     # pale pink tint, not flat white -- confirmed in the
                             # reference, bubbles pick up a faint tint of the
                             # gradient behind them rather than sitting flat white
    AI_BG = "#f8f6fb"       # pale lavender-white, distinct from the user's pink tint
    GRADIENT = (
        "qradialgradient(cx:0.22, cy:0.92, radius:1.15, fx:0.22, fy:0.92, "
        "stop:0 #f7cdec, stop:0.35 #ddc6f2, stop:0.65 #cfd8f7, stop:1 #ffffff)"
    )
    SUGGESTIONS = [
        "What can I ask you to do?",
        "Which one of my projects is performing the best?",
        "What projects should I be concerned about right now?",
    ]

    @staticmethod
    def _make_char_icon(char, color, size=64):
        """Renders `char` (an emoji or a symbol like the send arrow) onto a
        QPixmap via Qt's own font engine -- used both for the window icon
        (an emoji embedded directly in setWindowTitle()'s text renders
        through Windows' native title-bar font, which doesn't reliably
        support multi-codepoint emoji and can fall back to a placeholder
        glyph instead) and for the input field's embedded send icon."""
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        font = QtGui.QFont("Segoe UI Emoji")
        font.setPixelSize(int(size * 0.75))
        painter.setFont(font)
        painter.setPen(QtGui.QColor(color))
        painter.drawText(pix.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, char)
        painter.end()
        return QtGui.QIcon(pix)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compass — Ansys Help Assistant")
        self.setWindowIcon(self._make_char_icon("👩🏻‍💻", "#000"))
        self.resize(440, 520)
        self.setStyleSheet(f"QDialog {{ background: {self.GRADIENT}; }}")
        self.tutorial_context = ""
        self._thread = None
        self._worker = None
        self._answer_bubble = None  # the current turn's MessageBubble
        self._has_sent = False

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)

        sparkle = QtWidgets.QLabel("✨")
        sparkle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        sparkle.setFont(QtGui.QFont("Segoe UI Emoji", 20))
        sparkle.setStyleSheet("background:transparent; color:#222;")
        v.addWidget(sparkle)

        title = QtWidgets.QLabel("Ask our AI anything")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("background:transparent; color:#222; font-size:17px;")
        v.addWidget(title)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border:none; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        container = QtWidgets.QWidget()
        container.setStyleSheet("background: transparent;")
        self.messages_layout = QtWidgets.QVBoxLayout(container)
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(container)
        v.addWidget(self.scroll, stretch=1)

        # Suggestion chips -- only shown before the first message, matching
        # the reference's empty state.
        self.suggestions_box = QtWidgets.QWidget()
        self.suggestions_box.setStyleSheet("background:transparent;")
        sv = QtWidgets.QVBoxLayout(self.suggestions_box)
        sv.setContentsMargins(0, 0, 0, 6)
        sv.setSpacing(8)
        sug_label = QtWidgets.QLabel("Suggestions on what to ask Our AI")
        sug_label.setStyleSheet("background:transparent; color:#8a8a93; font-size:12px;")
        sv.addWidget(sug_label)
        chip_row = QtWidgets.QHBoxLayout()
        chip_row.setSpacing(8)
        for text in self.SUGGESTIONS:
            chip = QtWidgets.QPushButton(text)
            chip.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { background:#ffffff; color:#444; border:1px solid #ece9f0; "
                "border-radius:14px; padding:8px 14px; font-size:12px; text-align:left; }"
                "QPushButton:hover { background:#f7f3fb; }")
            chip.clicked.connect(lambda _checked, t=text: self._send_text(t))
            chip_row.addWidget(chip)
        sv.addLayout(chip_row)
        v.addWidget(self.suggestions_box)

        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Ask me anything about your projects")
        self.input.setFixedHeight(48)
        self.input.setStyleSheet(
            "QLineEdit { background:#ffffff; color:#222; border:1px solid #ece9f0; "
            "border-radius:24px; padding:0 44px 0 18px; font-size:15px; }"
            "QLineEdit:focus { border:1px solid #b9a8e0; }")
        send_action = QtGui.QAction(self._make_char_icon("➤", "#8a9ab3"), "", self.input)
        send_action.triggered.connect(self._send)
        self._send_action = send_action
        self.input.addAction(send_action, QtWidgets.QLineEdit.ActionPosition.TrailingPosition)
        self.input.returnPressed.connect(self._send)
        v.addWidget(self.input)

    def _send_text(self, text):
        self.input.setText(text)
        self._send()

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        QtCore.QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _add_bubble(self, caption, align="left", indent=0, **kwargs):
        bubble = MessageBubble(caption, parent=self.scroll, **kwargs)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if align == "right":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            if indent:
                row.addSpacing(indent)
            row.addWidget(bubble)
            row.addStretch(1)
        # Always APPEND (never insert before the vertical stretch __init__
        # added first) -- that stretch stays at index 0, so a short
        # conversation sits bunched near the BOTTOM of the scroll area with
        # blank space above it, matching the reference, and grows upward as
        # more turns are added instead of accumulating top-down.
        self.messages_layout.addLayout(row)
        return bubble

    def _send(self):
        question = self.input.text().strip()
        if not question or self._thread is not None:
            return  # a request is already in flight -- one at a time, see _cleanup_thread
        self.input.clear()
        if not self._has_sent:
            self._has_sent = True
            self.suggestions_box.setVisible(False)

        user_bubble = self._add_bubble(
            "ME", align="left", bg=self.USER_BG, text_color="#222")
        user_bubble.set_html(MessageBubble._escape(question))

        self._answer_bubble = self._add_bubble(
            "Compass", align="right", bg=self.AI_BG, text_color="#222")
        self._scroll_to_bottom()

        self.input.setEnabled(False)
        self._send_action.setEnabled(False)

        self._thread = QtCore.QThread(self)
        self._worker = ChatbotWorker(question, self.tutorial_context)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.token.connect(self._on_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_token(self, piece):
        self._answer_bubble.append_token(piece)
        self._scroll_to_bottom()

    def _on_finished(self, answer, sources):
        import markdown
        src_lines = "<br>".join(f"&nbsp;•&nbsp; {MessageBubble._escape(s)}" for s in sources)
        html = (
            markdown.markdown(answer)
            + f"<div style='margin-top:10px;padding-left:8px;border-left:2px solid #e5e3ea;"
              f"color:#9a96a8;font-size:12px;'><b>Sources</b><br>{src_lines}</div>")
        self._answer_bubble.set_html(html)
        self._scroll_to_bottom()

    def _on_failed(self, error):
        self._answer_bubble.set_html(
            f"<span style='color:{self.ERROR_COLOR}'>Sorry, Compass isn't reachable right "
            f"now ({MessageBubble._escape(error)}). Try again later or ask your "
            f"instructor.</span>")
        self._scroll_to_bottom()

    def _cleanup_thread(self):
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = None
        self._worker = None
        self._answer_bubble = None
        self.input.setEnabled(True)
        self._send_action.setEnabled(True)
        self.input.setFocus()


class Panel(QtWidgets.QWidget):
    """Step panel. Calls verify.verify_step() / locate.* and reacts -- never
    implements verification or element-finding itself."""

    def __init__(self, steps, tut_path):
        flags = (QtCore.Qt.WindowType.FramelessWindowHint
                 | QtCore.Qt.WindowType.WindowStaysOnTopHint
                 | QtCore.Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setWindowTitle("__TutGuidePanel__")  # never a real selector target
        self.steps = steps
        self.tut_path = tut_path  # re-read on report upload so rubric edits apply live
        self.i = 0
        self._started_at = time.time()  # stop requests older than this are stale
        self.manually_confirmed = False
        self.report_validation = None
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
        # The panel is frameless (no native title bar), so it needs its own
        # close button. A confirm dialog guards accidental mid-tutorial exits.
        self.btn_close = QtWidgets.QPushButton("✕")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setToolTip("Close the guide")
        self.btn_close.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(
            "QPushButton { background:transparent; color:#888; border:none; "
            "font-size:13px; }"
            "QPushButton:hover { color:#fff; background:#3a3a3a; border-radius:4px; }")
        self.btn_close.clicked.connect(self._confirm_close)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.lbl_prog)
        header.addStretch(1)
        header.addWidget(self.btn_close)
        v.addLayout(header)
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
        for w in (self.lbl_title, self.lbl_desc, self.lbl_hint, self.lbl_image, self.lbl_status):
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

        self.btn_upload = QtWidgets.QPushButton("Upload report…")
        self.btn_upload.setVisible(False)
        self.btn_upload.clicked.connect(self.upload_report)
        v.addWidget(self.btn_upload)

        self.btn_chatbot = QtWidgets.QPushButton("💬 Ask Compass")
        self.btn_chatbot.clicked.connect(self._open_chatbot)
        v.addWidget(self.btn_chatbot)
        self._chatbot_dialog = None  # created lazily on first use

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
        # Next is only enabled once the last step is complete (manual confirm
        # or a passing report), so a forward click there means "Finish".
        if self.i == len(self.steps) - 1 and delta > 0:
            self.close()
            return
        self.i = max(0, min(len(self.steps) - 1, self.i + delta))
        self.render_step()

    def mark_complete(self):
        self.manually_confirmed = True
        self._tick()

    def _confirm_close(self):
        # Closing mid-tutorial loses no server-side progress (steps are marked
        # in the web app), but confirm anyway -- ✕ sits right above Prev/Next.
        answer = QtWidgets.QMessageBox.question(
            self, "Close guide",
            "Close the tutorial guide? You can relaunch it any time from the "
            "web app or the terminal.",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.close()

    def upload_report(self):
        dialog = QtWidgets.QFileDialog(self, "Select generated report", str(REPO_ROOT))
        dialog.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        dialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter("Reports (*.docx *.txt *.md *.markdown *.html *.htm *.json *.pdf);;All Files (*)")
        if not dialog.exec():
            return
        selected = dialog.selectedFiles()
        if not selected:
            return
        path = selected[0]
        try:
            tutorial_data = json.loads(self.tut_path.read_text(encoding="utf-8"))
            self.report_validation = report_verify.validate_report(path, tutorial_data)
        except Exception as exc:
            self.report_validation = {
                "ok": False,
                "score": 0,
                "total": 1,
                "checks": [],
                "feedback": f"Report could not be checked: {exc}",
            }
        self.manually_confirmed = bool(self.report_validation.get("ok"))
        self._tick()

    def _open_chatbot(self):
        if self._chatbot_dialog is None:
            self._chatbot_dialog = ChatbotDialog(self)
        st = self._current()
        # Mirrors the architecture doc's "Context fetcher" (Section 8.1) --
        # in the real module this comes from querying the Student Track
        # App's own state automatically; here it's just the current step,
        # since that IS this app's state.
        self._chatbot_dialog.tutorial_context = (
            f"{st['_section']} — {st['title']} (step {self.i + 1}/{len(self.steps)})")
        self._chatbot_dialog.show()
        self._chatbot_dialog.raise_()
        self._chatbot_dialog.activateWindow()

    def render_step(self):
        st = self._current()
        self.manually_confirmed = False
        if st.get("step_id") != REPORT_STEP["step_id"]:
            self.report_validation = None
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
        # The web app's "Close guide" button reaches us via this sentinel
        # (see STOP_FILE above) -- no confirm dialog for a remote close, the
        # click over in the browser was the deliberate act. Compare mtime
        # instead of deleting: if several guides are somehow running, ALL of
        # them must see the request (the first deleter would hide it from the
        # rest). The file itself is cleaned up by the next launch's startup.
        try:
            stop_requested = STOP_FILE.stat().st_mtime >= self._started_at
        except OSError:
            stop_requested = False
        if stop_requested:
            self.close()
            return
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
        if st.get("step_id") == REPORT_STEP["step_id"]:
            verified = self.report_validation.get("ok") if self.report_validation else None
            if self.report_validation is None:
                status = "Upload a generated report to run the standard checks."
                next_ok = False
                color = "#9cf"
            elif verified:
                status = self.report_validation.get("feedback", "Report verified.")
                next_ok = True
                color = "#7e7"
            else:
                status = self.report_validation.get("feedback", "Report needs fixes.")
                next_ok = False
                color = "#fb7"
            located_txt = located_txt or "Report upload step"
        else:
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
        is_last = self.i == len(self.steps) - 1
        self.btn_next.setText("Finish" if is_last and next_ok else "Next →")
        # next_ok already encodes the step's own completion gate (manual
        # confirm, or a passing report on the report step) -- no extra
        # report requirement here, since tutorials without report_checks
        # have no report step at all.
        self.btn_next.setEnabled(next_ok)
        # Based on the ACTUAL runtime result, not a static guess from
        # verify.type -- a hardcoded `type in ("manual", "script")` check
        # here once missed verify.type=="uia" (and would miss any future
        # type) whenever it returns None because that check just isn't
        # implemented yet, leaving no way to advance past the step at all.
        self.btn_mark.setVisible(verified is None and st.get("step_id") != REPORT_STEP["step_id"])
        self.btn_mark.setEnabled(not self.manually_confirmed)
        self.btn_upload.setVisible(st.get("step_id") == REPORT_STEP["step_id"])
        self.btn_upload.setEnabled(not (self.report_validation and self.report_validation.get("ok")))

    def closeEvent(self, e):
        # Qt.Tool windows don't trigger quit-on-last-window-closed, so without
        # an explicit quit() every close path (Finish, the ✕ button, a remote
        # ansysguide://close) left a headless zombie process ticking forever
        # -- confirmed live: the stop check fired, close() ran, and the timer
        # kept printing anyway.
        self.timer.stop()
        self.highlight.close()
        if self._chatbot_dialog is not None:
            self._chatbot_dialog.close()
        super().closeEvent(e)
        QtWidgets.QApplication.quit()


REPORT_STEP = {
    "step_id": "report_01_upload",
    "app": "mechanical",
    "title": "Upload the generated report",
    "description": "Upload the Mechanical report you generated after finishing the tutorial. The system checks the report structure, the deformation results pages, and whether the final answer is represented correctly.",
    "selector": {
        "type": "window",
        "app": "mechanical"
    },
    "highlight": "none",
    "action": {
        "kind": "upload_report"
    },
    "verify": {
        "type": "manual",
        "prompt": "Upload the generated report and confirm it passes the standard checks."
    },
    "hints": [
        "Use the Mechanical HTML/PDF/DOCX report generated from the completed model.",
        "The validator looks for the Static Structural / Solution / Results structure and the deformation result pages.",
    ],
}


def build_runtime_steps(data):
    """Steps to run, straight from the tutorial dict. The synthetic report-
    upload checkpoint is appended only when the tutorial declares a
    report_checks rubric for it to grade against."""
    steps = load_steps(data)
    if not steps:
        sys.exit("tutorial has no steps")
    if data.get("report_checks"):
        REPORT_STEP["_section"] = "Generate the result"
        steps.append(REPORT_STEP)
    return steps


def main():
    tut_path = resolve_tutorial_path(sys.argv[1] if len(sys.argv) > 1 else None)
    if not tut_path.is_file():
        sys.exit(f"tutorial not found: {tut_path}")
    data = json.loads(tut_path.read_text(encoding="utf-8"))
    steps = build_runtime_steps(data)

    # A leftover stop request (e.g. "Close guide" clicked while no guide was
    # running) must not kill this fresh launch on its first tick.
    try:
        STOP_FILE.unlink()
    except OSError:
        pass

    qapp = QtWidgets.QApplication(sys.argv)
    panel = Panel(steps, tut_path)
    panel.show()
    title = data.get("title") or tut_path.stem
    print(f"Guiding {len(steps)} step(s) of \"{title}\". Make sure Ansys Workbench is open.")
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()

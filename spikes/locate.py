"""
Element location -- separate from the UI/panel script and from verification,
mirroring the real architecture's Element locator sub-piece of the Ansys
bridge (see CLAUDE.md / Student-Track-App-Build-Plan.md). Answers "where is
element X on screen right now, if anywhere" for the overlay to highlight.
Knows nothing about verification (verify.py) or about drawing the box
(guide_tut1.py owns the Highlight widget).

target_sequence(step) derives the ordered list of element names to highlight,
one stage at a time, from fields tut1.json already has -- no schema change:
  selector.via="File", selector.name="Save As"        -> ["File", "Save As"]
  right_click "Mesh" then menu_select "Generate Mesh"  -> ["Mesh", "Generate Mesh"]
  plain ribbon button (no via/then)                    -> [<selector.name>]

ElementLocator(app_key) finds a named element's screen rect inside one app's
window. This is the validated logic from earlier iterations of this spike:
  - connects to the app window itself (largest visible match for the title,
    not pywinauto's Application().connect(), which THROWS on 2+ matches),
  - excludes this script's own panel/highlight windows by process id (so it
    can never match its own text again, like it once matched its own step
    description that happened to contain the word "Save As"),
  - requires a candidate to be is_visible() right now, not just present in
    the tree with a non-zero rect (Workbench's closed menu items resolve in
    the UIA tree with a real rect even while invisible),
  - caches one descendants() walk per refresh_snapshot() call instead of
    re-walking the tree on every lookup (perf risk the build plan flagged).
"""

import os
from pathlib import Path

try:
    from pywinauto import Desktop
except ImportError:
    Desktop = None

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

try:
    import pytesseract
    for _candidate in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                       r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if Path(_candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = _candidate
            break
    # The installed Tesseract ships with no language data at all (its own
    # tessdata/ folder is empty -- confirmed by a real TesseractError: "Error
    # opening data file .../tessdata/eng.traineddata"). Program Files isn't
    # writable without admin rights, so eng.traineddata lives project-local
    # (spikes/tessdata/) instead. Passing `--tessdata-dir "<path>"` via
    # pytesseract's `config=` doesn't work on Windows: pytesseract splits
    # config with shlex(posix=False), which does NOT strip quotes, so the
    # literal quote characters end up inside the path tesseract opens
    # (confirmed: a real TesseractError showed `"<path>"/eng.traineddata`
    # with quotes baked into the failing path). TESSDATA_PREFIX as an env
    # var has no such quoting step -- it's inherited by the subprocess as-is.
    _TESSDATA_DIR = Path(__file__).resolve().parent / "tessdata"
    if (_TESSDATA_DIR / "eng.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(_TESSDATA_DIR)
except ImportError:
    pytesseract = None

DEBUG = True

APP_TITLES = {"workbench": "Workbench", "spaceclaim": "SpaceClaim", "mechanical": "Mechanical"}

OCR_UPSCALE = 3  # Toolbox row text is ~12-14px tall; OCR accuracy improves a lot once upscaled


def _toolbox_rect(title_hint="Workbench"):
    """Live screen rect of the Toolbox CONTENT panel, found via the win32
    backend's window-handle geometry, re-detected on every call (not cached)
    so it survives window move/resize. Diagnostic probes (since removed --
    see tut1.json _notes.workbench_uia_finding_2026-06 and
    .workbench_win32_finding_2026-06) confirmed the Toolbox has zero UIA or
    per-row win32 accessibility -- but the panel HWND itself is real: a
    left-docked, narrow (~240-360px), tall content pane with an adjacent
    vertical scrollbar sharing its top/bottom (confirmed shape: content pane
    L4,T183-R308,B954 + scrollbar L288-308)."""
    if Desktop is None:
        return None
    try:
        wins = [w for w in Desktop(backend="win32").windows()
                if title_hint.lower() in (w.window_text() or "").lower() and w.is_visible()]
    except Exception:
        return None
    if not wins:
        return None
    wins.sort(key=lambda w: w.rectangle().width() * w.rectangle().height(), reverse=True)
    win = wins[0]
    try:
        children = win.descendants()
        win_left = win.rectangle().left
    except Exception:
        return None
    scrollbars = [c for c in children if "scrollbar" in (c.element_info.class_name or "").lower()]
    for c in children:
        try:
            r = c.rectangle()
        except Exception:
            continue
        w_, h_ = r.width(), r.height()
        if not (240 <= w_ <= 360 and h_ > 400):
            continue
        if r.left - win_left > 60:
            continue
        if not any(abs(sb.rectangle().top - r.top) < 15 and abs(sb.rectangle().bottom - r.bottom) < 15
                   for sb in scrollbars):
            continue
        return (r.left, r.top, r.right, r.bottom)
    return None


def schematic_rect(title_hint="Workbench"):
    """Live screen rect of the Project Schematic canvas: everything to the
    right of the Toolbox panel, spanning the Toolbox's own vertical extent
    (the two panels sit side by side at the same height in Workbench's main
    client area). Public (unlike _toolbox_rect) because verify.py scopes its
    "has a system been dropped onto the schematic" OCR check to this region
    on purpose -- the Toolbox's own "Static Structural" template row would
    otherwise be an obvious false positive for that check."""
    tb = _toolbox_rect(title_hint)
    if tb is None or Desktop is None:
        return None
    try:
        wins = [w for w in Desktop(backend="win32").windows()
                if title_hint.lower() in (w.window_text() or "").lower() and w.is_visible()]
    except Exception:
        return None
    if not wins:
        return None
    wins.sort(key=lambda w: w.rectangle().width() * w.rectangle().height(), reverse=True)
    win_rect = wins[0].rectangle()
    return (tb[2], tb[1], win_rect.right, tb[3])


OCR_RETRIES = 2  # Tesseract is genuinely flaky frame-to-frame on the exact same,
                 # unchanged row (confirmed live: identical toolbox rect, one
                 # tick reads "Static Structural" fine, the next tick doesn't
                 # see it at all among 80+ other correctly-read words) -- so a
                 # single grab+OCR isn't trustworthy. Re-grab and re-run OCR a
                 # couple times within the same call before reporting NOT FOUND.

SIDE_PAD = 14  # extra horizontal margin baked into the box on top of the
               # icon-coverage extension, so the box doesn't hug the text/icon
               # edge-to-edge


def _ocr_words(rect):
    shot = ImageGrab.grab(bbox=rect)
    frame = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
    frame = cv2.resize(frame, None, fx=OCR_UPSCALE, fy=OCR_UPSCALE, interpolation=cv2.INTER_CUBIC)
    return pytesseract.image_to_data(frame, output_type=pytesseract.Output.DICT)


def _match_phrase_bbox(data, target_words):
    """Find `target_words` (already lowercased/split) as consecutive words on
    one OCR line within `data` (one pytesseract.image_to_data() result).
    Returns (left, top, right, bottom) in upscaled-image pixel coords, or
    None. Factored out of locate_text() so multi-phrase checks (see
    texts_found()) can reuse a SINGLE OCR pass for several phrases instead
    of paying for one Tesseract invocation per phrase per tick."""
    n = len(target_words)
    words = data["text"]
    for i in range(len(words) - n + 1):
        chunk = [(words[i + j] or "").strip().lower() for j in range(n)]
        if chunk != target_words:
            continue
        if len({data["line_num"][i + j] for j in range(n)}) > 1:
            continue  # the words must sit on the same OCR line
        if len({data["block_num"][i + j] for j in range(n)}) > 1:
            continue
        xs = [data["left"][i + j] for j in range(n)]
        ys = [data["top"][i + j] for j in range(n)]
        rights = [data["left"][i + j] + data["width"][i + j] for j in range(n)]
        bottoms = [data["top"][i + j] + data["height"][i + j] for j in range(n)]
        return min(xs), min(ys), max(rights), max(bottoms)
    return None


def locate_text(target_text, region_rect=None):
    """Find `target_text` (e.g. "Static Structural") live on screen via OCR,
    scoped to `region_rect` (defaults to the Toolbox panel rect). Returns
    (left, top, right, bottom) in screen coords, or None.

    Image-template matching was tried first and rejected: it locked onto the
    "Modal" row instead of "Static Structural" even when searching the EXACT
    screenshot the template was cropped from (score 0.58, beating the real
    match), because every Toolbox row shares the same icon+text layout and
    raw pixel correlation doesn't actually read the text. OCR matches on the
    real string content instead, which is what actually distinguishes rows."""
    if pytesseract is None or cv2 is None or np is None or ImageGrab is None:
        if DEBUG:
            print("[debug] locate_text: pytesseract/opencv/numpy/Pillow not installed")
        return None
    rect = region_rect or _toolbox_rect()
    if rect is None:
        if DEBUG:
            print("[debug] locate_text: couldn't find the live Toolbox panel rect")
        return None

    target_words = target_text.lower().split()
    data = None
    for attempt in range(OCR_RETRIES + 1):
        data = _ocr_words(rect)
        bbox = _match_phrase_bbox(data, target_words)
        if bbox:
            l, t, r, b = (v / OCR_UPSCALE for v in bbox)
            # Extend the left edge to also cover the row's icon, which OCR
            # can't see at all (it's a glyph, not text) -- Toolbox icons sit
            # immediately left of the label and are roughly as tall as the
            # text row. Then pad both sides further so the box has visible
            # breathing room instead of hugging the text/icon edge-to-edge.
            row_h = b - t
            l = max(0, l - row_h * 1.3 - SIDE_PAD)
            r = r + SIDE_PAD
            result = (rect[0] + l, rect[1] + t, rect[0] + r, rect[1] + b)
            if DEBUG:
                tail = f" (attempt {attempt + 1}/{OCR_RETRIES + 1})" if attempt else ""
                print(f"[debug] locate_text({target_text!r}) -> {result}{tail}")
            return result
    if DEBUG:
        seen = [w for w in data["text"] if w.strip()]
        print(f"[debug] locate_text({target_text!r}) -> NOT FOUND after "
              f"{OCR_RETRIES + 1} attempt(s). OCR read {len(seen)} non-empty "
              f"word(s) in toolbox rect {rect}: {seen[:40]}")
    return None


def texts_found(texts, region_rect):
    """Returns the SUBSET of `texts` that OCR could read within region_rect,
    UNIONED across up to OCR_RETRIES+1 retried attempts -- a phrase counts
    if ANY attempt reads it. Confirmed live (not a hypothetical): the exact
    same unchanged schematic block had "Engineering Data"/"Setup"/"Solution"/
    "Results" read fine but "Geometry"/"Model" missed on one tick's single
    OCR pass -- a DIFFERENT word can drop out on each attempt, so requiring
    every phrase to land in the SAME single attempt (the original version of
    this check) under-reports even when every phrase is genuinely on screen
    and has been read correctly at least once."""
    if pytesseract is None or cv2 is None or np is None or ImageGrab is None:
        if DEBUG:
            print("[debug] texts_found: pytesseract/opencv/numpy/Pillow not installed")
        return set()
    if region_rect is None:
        if DEBUG:
            print("[debug] texts_found: no region rect given")
        return set()
    target_lists = {t: t.lower().split() for t in texts}
    found = set()
    for _attempt in range(OCR_RETRIES + 1):
        data = _ocr_words(region_rect)
        for t, tw in target_lists.items():
            if t not in found and _match_phrase_bbox(data, tw) is not None:
                found.add(t)
        if len(found) == len(texts):
            break
    if DEBUG:
        missing = [t for t in texts if t not in found]
        print(f"[debug] texts_found({texts!r}) -> found={sorted(found)} missing={missing}")
    return found


def menu_chain(value):
    return [part.strip() for part in value.split(">")] if value else []


def target_sequence(step):
    sel = step.get("selector", {})
    action = step.get("action", {})
    name = sel.get("name")
    if sel.get("type") != "uia" or not name:
        return []
    via = sel.get("via")
    if via:
        return [via, name]
    if action.get("kind") == "menu_select" and action.get("value") and not action.get("then"):
        return [name] + menu_chain(action["value"])
    if action.get("kind") == "right_click" and action.get("then") == "menu_select" and action.get("value"):
        return [name] + menu_chain(action["value"])
    return [name]


class ElementLocator:
    """One instance per app. Create lazily as steps need different apps."""

    def __init__(self, app_key):
        self.title = APP_TITLES.get(app_key, app_key)
        self._win = None
        self._target_pid = None
        self._own_pid = os.getpid()
        self._snapshot = []

    def _is_own_window(self, w):
        try:
            return w.element_info.process_id == self._own_pid
        except Exception:
            return False

    def _window(self):
        if self._win is not None:
            return self._win
        if Desktop is None:
            return None
        candidates = []
        try:
            for w in Desktop(backend="uia").windows():
                if self._is_own_window(w):
                    continue
                try:
                    title = w.window_text() or ""
                    if self.title.lower() not in title.lower():
                        continue
                    if not w.is_visible():
                        continue
                    rect = w.rectangle()
                    area = rect.width() * rect.height()
                except Exception:
                    continue
                if area > 0:
                    candidates.append((area, title, w))
        except Exception as e:
            if DEBUG:
                print(f"[debug] window enumeration failed: {e}")
            return None
        if not candidates:
            if DEBUG:
                print(f"[debug] no visible window matching '{self.title}'")
            return None
        candidates.sort(key=lambda c: c[0], reverse=True)
        _, title, w = candidates[0]
        self._win = w
        try:
            self._target_pid = w.element_info.process_id
        except Exception:
            self._target_pid = None
        if DEBUG:
            print(f"[debug] connected to window: {title!r} "
                  f"({len(candidates)} candidate(s), pid={self._target_pid})")
        return self._win

    def refresh_snapshot(self):
        """Call ONCE per tick before any locate() calls in that tick."""
        win = self._window()
        try:
            self._snapshot = win.descendants() if win else []
        except Exception as e:
            self._snapshot = []
            if DEBUG:
                print(f"[debug] descendants() walk failed: {e}")

    @staticmethod
    def _match(ctrls, name):
        """Match by name, visibility, AND prefer the SMALLEST matching box.
        Some native menu implementations report the currently-highlighted
        item's name on the WHOLE popup container too (confirmed: a real box
        wrapped the entire File dropdown, not just 'Save As...'), so the
        first name match isn't necessarily the right element -- the specific
        leaf row is always much smaller than any wrapping container that
        happens to share its name."""
        if not name:
            return None
        candidates = []
        for ctrl in ctrls:
            try:
                cname = ctrl.element_info.name or ""
            except Exception:
                continue
            if name.lower() not in cname.lower():
                continue
            try:
                visible = ctrl.is_visible()
            except Exception:
                visible = True
            try:
                r = ctrl.rectangle() if visible else None
            except Exception:
                r = None
            ok = bool(r and r.width() > 0 and r.height() > 0)
            area = (r.width() * r.height()) if ok else None
            if DEBUG:
                print(f"[debug]   candidate {cname!r} visible={visible} rect={r} area={area} -> "
                      f"{'MATCH' if ok else 'skip'}")
            if ok:
                candidates.append((area, r))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0])
        _, r = candidates[0]
        return (r.left, r.top, r.right, r.bottom)

    def locate(self, name):
        """Return (left, top, right, bottom) or None. Only ever called with
        the OUTER/topmost name of a sequence (e.g. "File") -- guide_tut1.py
        no longer attempts to box items inside a transient native popup,
        since Workbench's dropdown rows don't expose a stable per-row name
        (matching flipped between "found, wrong size" and "not found"
        depending on mouse position). The popup-scoped fallback below is
        still here for right-click context menus elsewhere in the tutorial,
        where the menu itself IS the target (not a row inside it)."""
        rect = self._match(self._snapshot, name)
        if rect:
            if DEBUG:
                print(f"[debug] locate({name!r}) -> {rect} (main window)")
            return rect
        if Desktop is not None and self._target_pid is not None:
            try:
                for w in Desktop(backend="uia").windows():
                    if self._is_own_window(w):
                        continue
                    try:
                        if w.element_info.process_id != self._target_pid:
                            continue
                        fb = self._match(w.descendants(), name)
                    except Exception:
                        fb = None
                    if fb:
                        if DEBUG:
                            print(f"[debug] locate({name!r}) -> {fb} (popup {w.window_text()!r})")
                        return fb
            except Exception:
                pass
        if DEBUG:
            sample = []
            for ctrl in self._snapshot:
                try:
                    n = ctrl.element_info.name
                except Exception:
                    n = None
                if n:
                    sample.append(n)
                if len(sample) >= 40:
                    break
            print(f"[debug] locate({name!r}) -> NOT FOUND. "
                  f"main-window snapshot has {len(self._snapshot)} controls total; "
                  f"{len(sample)} have a non-empty name. sample: {sample}")
        return None

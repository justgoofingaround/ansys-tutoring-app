"""Render a tutorial JSON into a formatted PDF — a realistic source document
for testing the PDF -> tutorial conversion round-trip.

    .venv\\Scripts\\python tools\\make_sample_pdf.py [tutorial.json] [out.pdf]

Defaults: mock_server/data/m07_tut.json -> server_data/samples/sample_tutorial.pdf
"""

import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parents[1]
MARGIN = 72
WIDTH, HEIGHT = 595, 842  # A4 points


def main(argv: list[str]) -> None:
    src = Path(argv[0]) if argv else REPO_ROOT / "mock_server" / "data" / "m07_tut.json"
    out = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "server_data" / "samples" / "sample_tutorial.pdf"
    data = json.loads(src.read_text(encoding="utf-8-sig"))

    doc = fitz.open()

    def new_page():
        return doc.new_page(width=WIDTH, height=HEIGHT)

    # Title page
    page = new_page()
    writer = fitz.TextWriter(page.rect)
    title_font = fitz.Font("helv")
    y = MARGIN + 40
    writer.append((MARGIN, y), data.get("title", src.stem), font=title_font, fontsize=20)
    y += 50
    for line in _wrap(data.get("problem", ""), 80):
        writer.append((MARGIN, y), line, font=title_font, fontsize=12)
        y += 18
    writer.write_text(page)

    # One page per section, numbered steps with hints
    for sec in data.get("sections", []):
        page = new_page()
        writer = fitz.TextWriter(page.rect)
        y = MARGIN
        writer.append((MARGIN, y), sec.get("section", "Section"), font=title_font, fontsize=16)
        y += 30
        for n, st in enumerate(sec.get("steps", []), start=1):
            if y > HEIGHT - MARGIN - 60:
                writer.write_text(page)
                page = new_page()
                writer = fitz.TextWriter(page.rect)
                y = MARGIN
            writer.append((MARGIN, y), f"Step {n}: {st.get('title', '')}",
                          font=title_font, fontsize=12)
            y += 16
            for line in _wrap(st.get("description", ""), 90):
                writer.append((MARGIN + 14, y), line, font=title_font, fontsize=10)
                y += 13
            for hint in st.get("hints") or []:
                for line in _wrap(f"Tip: {hint}", 88):
                    writer.append((MARGIN + 14, y), line, font=title_font, fontsize=9)
                    y += 12
            y += 8
        writer.write_text(page)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    print(f"wrote {out} ({doc.page_count} pages) from {src.name}")


def _wrap(text: str, width: int) -> list[str]:
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


if __name__ == "__main__":
    main(sys.argv[1:])

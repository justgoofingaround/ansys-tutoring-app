"""
Parses one source document into a list of (text, page_or_section_label)
pairs -- kept separate from chunking.py on purpose, mirroring this project's
established "one concern per module" convention (see CLAUDE.md): parsing
knows about file formats, chunking knows about token budgets, neither knows
about the other.

PDFs are parsed PAGE BY PAGE (not as one giant blob) specifically so a chunk
built from them can carry an accurate page number for citation -- the
architecture doc's citation requirement (Section 8.1/8.2: "every chatbot
answer must cite its source (book, section, page)") is unsatisfiable if we
lose page boundaries during parsing.
"""

import re

import fitz  # PyMuPDF
from bs4 import BeautifulSoup


def parse_pdf(path):
    """Returns [(page_text, page_number), ...], 1-indexed pages, skipping
    blank/near-blank pages (cover pages, section dividers) since they'd only
    ever produce noise chunks."""
    pages = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if len(text) >= 40:  # skip near-blank pages
                pages.append((text, i + 1))
    return pages


def parse_html(path):
    """Returns [(section_text, heading), ...] -- HTML doesn't have pages, so
    citations use the nearest preceding heading (h1-h3) as the "section"
    label instead, falling back to the filename if no heading precedes any
    content (e.g. a single-section page)."""
    with open(path, encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    sections = []
    current_heading = path.stem
    current_text = []

    def flush():
        text = " ".join(current_text).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) >= 40:
            sections.append((text, current_heading))

    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "pre"]):
        if el.name in ("h1", "h2", "h3"):
            flush()
            current_heading = el.get_text(strip=True) or current_heading
            current_text = []
        else:
            txt = el.get_text(" ", strip=True)
            if txt:
                current_text.append(txt)
    flush()
    return sections


def parse_document(path):
    """Dispatches on file extension. Returns [(text, label), ...] where
    `label` is a page number (PDF) or heading string (HTML) -- the caller
    (chunking.py) doesn't need to know which."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix in (".html", ".htm"):
        return parse_html(path)
    raise ValueError(f"parse_document: unsupported file type {suffix!r} for {path}")

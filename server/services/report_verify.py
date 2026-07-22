"""Report validation against a tutorial's report_checks rubric.

Promoted from spikes/report_verify.py (which now re-exports this module so
the desktop guide keeps working). The student uploads a generated report;
this performs the rubric checks plus an optional local-LLM review and
returns structured feedback the UI can display.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self):
        return " ".join(self.parts)


def _normalise(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def _read_text_file(path):
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".csv", ".log"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(_read_html_text(path))
        return html.unescape(parser.text())
    if suffix == ".docx":
        return _read_docx_text(path)
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(raw, dict):
            return json.dumps(raw, indent=2, sort_keys=True)
        return json.dumps(raw)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "PDF upload support needs the optional 'pypdf' package installed"
            ) from exc

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported report format: {path.suffix or '<none>'}")


def _read_html_text(path):
    raw = path.read_bytes()
    if b"\x00" in raw[:512]:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore")


def _read_docx_text(path):
    """Extract plain text from a .docx without needing an extra dependency."""

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as fh:
                root = ET.fromstring(fh.read())
    except zipfile.BadZipFile as exc:
        raise ValueError("Selected .docx file is not a valid Word document") from exc
    except KeyError as exc:
        raise ValueError("Selected .docx file is missing Word document content") from exc

    paragraphs = []
    for para in root.findall(".//w:p", ns):
        pieces = []
        for node in para.findall(".//w:t", ns):
            if node.text:
                pieces.append(node.text)
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _report_excerpt(text, rubric, limit_lines=70):
    """Pull out the report lines most relevant to a human/LLM review."""

    keywords = []
    keywords.extend(rubric.get("required_sections", []))
    keywords.extend(rubric.get("preferred_sections", []))
    keywords.extend(rubric.get("must_contain", []))
    keywords.extend([
        "Static Structural",
        "Solution",
        "Results",
        "Total Deformation",
        "Equivalent Stress",
        "Structural Steel",
    ])
    keywords = [kw.lower() for kw in keywords if kw]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:8000]

    hit_indexes = []
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(kw in lower for kw in keywords):
            hit_indexes.extend(range(max(0, idx - 1), min(len(lines), idx + 2)))

    if not hit_indexes:
        return "\n".join(lines[:limit_lines])

    excerpt = []
    seen = set()
    for idx in sorted(set(hit_indexes)):
        if idx in seen:
            continue
        seen.add(idx)
        excerpt.append(lines[idx])
        if len(excerpt) >= limit_lines:
            break
    return "\n".join(excerpt)


def _review_report_with_llm(text, rubric, validation_summary, guidelines=None):
    """Run a local-only LLM review over the extracted report text.

    `guidelines` is the instructor's free-text report-checking criteria
    (tutorials.report_guidelines, set in the web app). When present it is
    inserted as a clearly delimited prompt section so the review judges the
    report against the instructor's expectations; when absent the prompt is
    byte-identical to the guideline-less version."""

    try:
        import ollama
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        return {
            "available": False,
            "model": None,
            "overall": "LLM review unavailable in this environment.",
            "caveats": [f"Local LLM could not be loaded: {exc}"],
            "strengths": [],
            "suggestions": [],
        }

    try:
        from config import OLLAMA_MODEL  # chatbot_spike is added to sys.path by the guide
    except Exception:
        OLLAMA_MODEL = "gemma3:4b"

    excerpt = _report_excerpt(text, rubric)
    guidelines_block = ""
    if guidelines and guidelines.strip():
        guidelines_block = f"""
Instructor's report-checking guidelines for this tutorial. Treat these as the
primary review criteria, in addition to the checklist. They describe what the
instructor wants to see; judge the report against them, but still return ONLY
the JSON object described above.
--- BEGIN INSTRUCTOR GUIDELINES ---
{guidelines.strip()[:4000]}
--- END INSTRUCTOR GUIDELINES ---
"""
    prompt = f"""
You are reviewing an Ansys Mechanical report for a student lab assignment.
Stay local-only and use ONLY the report excerpt and checklist summary below.
Do not invent content that is not present.
This report is an exported Mechanical HTML/PDF/DOCX file, so some values may live inside rendered figures rather than plain text.
Only make claims that are directly supported by the excerpt. If a numeric result is not visible in text, say the text extraction could not confirm it.
Do NOT claim the report lacks results if the excerpt clearly contains result-page headings such as Total Deformation or Equivalent Stress.

Return valid JSON with exactly these keys:
- overall: one short sentence summarizing the review
- strengths: array of 1-3 concise positive observations
- caveats: array of 1-4 concrete issues, omissions, ambiguities, or weak spots
- suggestions: array of 1-4 practical fixes the student can make
- confidence: one of low, medium, high
{guidelines_block}
Checklist summary:
{json.dumps(validation_summary, indent=2, ensure_ascii=False)}

Report excerpt:
{excerpt}

Focus on whether the student documented the model setup, result pages, and interpretation clearly enough for a grader to follow the work progress.
""".strip()

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a strict but helpful lab-report reviewer."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0, "num_predict": 260},
            format="json",
        )
        payload = response["message"]["content"]
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("LLM review did not return a JSON object")
        return {
            "available": True,
            "model": OLLAMA_MODEL,
            "overall": str(data.get("overall", "" )).strip(),
            "strengths": [str(item).strip() for item in data.get("strengths", []) if str(item).strip()],
            "caveats": [str(item).strip() for item in data.get("caveats", []) if str(item).strip()],
            "suggestions": [str(item).strip() for item in data.get("suggestions", []) if str(item).strip()],
            "confidence": str(data.get("confidence", "")).strip().lower() or "unknown",
        }
    except Exception as exc:  # pragma: no cover - runtime/model failures are user-environment specific
        return {
            "available": False,
            "model": OLLAMA_MODEL,
            "overall": "LLM review could not be completed.",
            "caveats": [f"Local model review failed: {exc}"],
            "strengths": [],
            "suggestions": [],
            "confidence": "unknown",
        }


def _has_phrase(text, phrase):
    return _normalise(phrase) in _normalise(text)


def _find_numeric_values(text):
    values = []
    for match in re.finditer(r"(?<!\w)[+-]?(?:\d*\.\d+|\d+\.?)(?:e[+-]?\d+)?", text, re.IGNORECASE):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return values


SECTION_ALIASES = {
    "static structural": ["static structural"],
    "solution": ["solution"],
    "results": ["results"],
    "total deformation": ["total deformation"],
    "equivalent stress": ["equivalent stress"],
    "structural steel": ["structural steel", "steel"],
}


def _section_matches(text, section):
    variants = SECTION_ALIASES.get(section.lower(), [section])
    return any(_has_phrase(text, variant) for variant in variants)


def _check_items(text, values, prefix, severity="error"):
    checks = []
    for value in values:
        ok = _has_phrase(text, value)
        checks.append({
            "name": f"{prefix}:{value}",
            "ok": ok,
            "severity": severity,
            "message": (
                f"Found {prefix.replace('_', ' ')} '{value}'"
                if ok
                else f"Missing {prefix.replace('_', ' ')} '{value}'"
            ),
        })
    return checks


def _format_feedback(checks, ok):
    passed = [check["message"] for check in checks if check["ok"]]
    failed = [check["message"] for check in checks if not check["ok"]]
    warnings = [check["message"] for check in checks if check.get("severity") == "warning" and not check["ok"]]

    lines = ["Report verified." if ok else "Report needs fixes."]
    if passed:
        lines.append("What looks good:")
        lines.extend(f"- {message}" for message in passed)
    if failed:
        lines.append("What to fix:")
        lines.extend(f"- {message}" for message in failed)
    if warnings:
        lines.append("Helpful guidance:")
        lines.extend(f"- {message}" for message in warnings)
        lines.append("- Make sure the report includes the result page and figure caption for the final deformation output.")
    if ok and not warnings:
        lines.append("The report structure matches the Mechanical export we expect students to submit.")
    return "\n".join(lines)


def validate_report(report_path, tutorial_data, use_llm=True, guidelines=None):
    """Validate a generated report against the tutorial rubric.

    use_llm=False skips the local-Ollama review (tests; machines without
    Ollama). `guidelines` is optional instructor free text threaded into the
    LLM review only — the deterministic ok/score/checks below never depend
    on it (and the desktop guide, which calls this positionally without
    guidelines, keeps working unchanged). Returns a dict with:
      ok: bool
      score: int
      total: int
      checks: list of {name, ok, message}
      feedback: short human-readable summary
    """

    path = Path(report_path)
    rubric = tutorial_data.get("report_checks", {})
    text = _read_text_file(path)
    checks = []

    required_sections = rubric.get("required_sections", [])
    for section in required_sections:
        ok = _section_matches(text, section)
        checks.append({
            "name": f"section:{section}",
            "ok": ok,
            "severity": "error",
            "message": f"Found section heading '{section}'" if ok else f"Missing section heading '{section}'",
        })

    preferred_sections = rubric.get("preferred_sections", [])
    checks.extend(_check_items(text, preferred_sections, "preferred_section", severity="warning"))

    must_contain = rubric.get("must_contain", [])
    for phrase in must_contain:
        ok = _has_phrase(text, phrase)
        checks.append({
            "name": f"phrase:{phrase}",
            "ok": ok,
            "severity": "error",
            "message": f"Found required fact '{phrase}'" if ok else f"Missing required fact '{phrase}'",
        })

    expected = rubric.get("expected_result", {})
    expected_value = expected.get("value")
    tolerance = float(expected.get("tolerance", 0.0) or 0.0)
    aliases = expected.get("aliases", [])
    units = expected.get("units")

    numeric_ok = False
    numeric_message = ""
    if expected_value is not None:
        for alias in aliases:
            if _has_phrase(text, alias):
                numeric_ok = True
                numeric_message = f"Found expected result alias '{alias}'"
                break

        if not numeric_ok:
            values = _find_numeric_values(text)
            for value in values:
                if abs(value - float(expected_value)) <= tolerance:
                    if units and not _has_phrase(text, units):
                        numeric_message = (
                            f"Found close result {value}, but missing units '{units}'"
                        )
                        numeric_ok = False
                    else:
                        numeric_ok = True
                        numeric_message = f"Found result {value} within tolerance {tolerance}"
                    break
            if not numeric_ok and not numeric_message:
                numeric_message = (
                    f"Did not find a result close to {expected_value} within tolerance {tolerance}"
                )

        checks.append({
            "name": "expected_result",
            "ok": numeric_ok,
            "severity": "warning",
            "message": numeric_message or "No textual numeric result found; check the deformation caption/summary.",
        })

    hard_checks = [check for check in checks if check.get("severity") != "warning"]
    score = sum(1 for check in hard_checks if check["ok"])
    total = len(hard_checks)
    ok = score == total
    if use_llm:
        llm_review = _review_report_with_llm(
            text,
            rubric,
            {
                "ok": ok,
                "score": score,
                "total": total,
                "checks": [
                    {"name": check["name"], "ok": check["ok"], "message": check["message"]}
                    for check in checks
                ],
            },
            guidelines=guidelines,
        )
    else:
        llm_review = {
            "available": False,
            "model": None,
            "overall": "LLM review disabled.",
            "caveats": [],
            "strengths": [],
            "suggestions": [],
            "confidence": "unknown",
        }
    feedback = _format_feedback(checks, ok)
    if llm_review.get("available"):
        feedback += "\n\nLLM review: " + (llm_review.get("overall") or "")
        if llm_review.get("strengths"):
            feedback += "\nStrengths:\n" + "\n".join(f"- {item}" for item in llm_review["strengths"])
        if llm_review.get("caveats"):
            feedback += "\nCaveats:\n" + "\n".join(f"- {item}" for item in llm_review["caveats"])
        if llm_review.get("suggestions"):
            feedback += "\nSuggestions:\n" + "\n".join(f"- {item}" for item in llm_review["suggestions"])

    return {
        "ok": ok,
        "score": score,
        "total": total,
        "checks": checks,
        "feedback": feedback,
        "llm_review": llm_review,
        "text": text,
    }
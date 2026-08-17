"""PDF -> tutorial JSON conversion (instructor upload).

Backend: local Ollama when enabled and reachable, else the OpenAI-compatible
cloud API (CHATBOT_API_KEY, same Groq-by-default config the cloud chatbot
uses). The PDF is instructor-authored course material — never student data —
so the cloud fallback does not touch the FERPA invariant (which is about
student data specifically).

The LLM's job is deliberately small: it extracts prose (title, problem,
per-chunk step titles/descriptions/hints). Everything the tutorial
validator ERRORs on — step_ids, highlight, verify, apps — is assembled
deterministically in Python, so a generated draft always validates. Steps
come out in the safe minimal shape (highlight "none", manual verify), the
same convention the hand-authored m01-m08 tutorials use; instructors
refine selectors/images later by editing the JSON.

Staged calls, not one giant generation (gemma3:4b is small): one metadata
call over the opening pages, then one steps call per 3-page chunk. Each
chunk failing is survivable (skipped + counted); a whole-document failure
is not (GenerationFailedError).
"""

import json
import re
import time

MAX_PAGES = 40
PAGES_PER_CHUNK = 3
CHUNK_CHAR_CAP = 6000
MAX_STEPS_PER_CHUNK = 10

APPS = ("workbench", "spaceclaim", "discovery", "mechanical")
APP_PREFIX = {"workbench": "wb", "spaceclaim": "sc", "discovery": "di", "mechanical": "me"}
RESERVED_STEP_IDS = {"report_01_upload"}


class PdfConversionError(Exception):
    """Base for conversion failures; router maps subclasses to statuses."""


class PdfExtractionError(PdfConversionError):
    """Not a PDF / no extractable text / too many pages (-> 422)."""


class LlmUnavailableError(PdfConversionError):
    """No usable backend: Ollama off/unreachable and no cloud key (-> 503)."""


class GenerationFailedError(PdfConversionError):
    """The model produced nothing usable after retries (-> 502)."""


METADATA_PROMPT = """You are converting an Ansys simulation tutorial PDF into structured JSON.
Below is the beginning of the tutorial text.

Return JSON only, exactly: {{"title": "...", "problem": "..."}}
- title: the tutorial's title, one line, no numbering artifacts.
- problem: 2-4 sentences describing the engineering problem and goal, written for a student.

TEXT:
{text}"""

STEPS_PROMPT = """You are converting part of an Ansys simulation tutorial into steps a student follows.
Return JSON only, exactly:
{{"section_title": "...", "steps": [{{"app": "...", "title": "...", "description": "...", "hints": ["..."]}}]}}

Rules:
- 1 to {max_steps} steps, in the order the student performs them.
- Each step is ONE concrete action (open a file, click a menu item, select faces, set a value, solve, review a result).
- description: 1-3 imperative sentences; keep exact menu paths, file names, and values from the text.
- app: which Ansys app the step happens in - one of: workbench, spaceclaim, discovery, mechanical.
- hints: 0-2 short tips, or [].
- Ignore page headers, footers, copyright lines, and slide numbers.
- If this text contains no actionable steps, return {{"section_title": "", "steps": []}}.

TEXT (pages {a}-{b}):
{text}"""


def _extract_pages(raw: bytes) -> list[str]:
    import fitz  # PyMuPDF — already a chatbot_spike dependency

    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise PdfExtractionError("not_a_pdf: the file could not be opened as a PDF")
    with doc:
        if doc.page_count > MAX_PAGES:
            raise PdfExtractionError(
                f"too_many_pages: {doc.page_count} pages (max {MAX_PAGES})"
            )
        pages = [page.get_text() for page in doc]
    if not "".join(pages).strip():
        raise PdfExtractionError(
            "no_text: the PDF has no extractable text (scanned/image-only PDFs "
            "are not supported — export a text-based PDF)"
        )
    return pages


def _resolve_model() -> str:
    try:
        from config import OLLAMA_MODEL  # chatbot_spike config (sys.path bridge)

        return OLLAMA_MODEL
    except Exception:
        return "gemma3:4b"


def _ollama_chat_json(model: str, prompt: str) -> dict:
    """One format="json" chat call. Connection-level failures raise
    LlmUnavailableError; a bad payload raises ValueError (caller retries)."""
    try:
        import ollama
    except Exception as exc:
        raise LlmUnavailableError(f"ollama package unavailable: {exc}")
    try:
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"num_predict": 2048, "temperature": 0},
        )
    except Exception as exc:
        raise LlmUnavailableError(f"ollama not reachable: {exc}")
    data = json.loads(resp["message"]["content"])  # ValueError on garbage
    if not isinstance(data, dict):
        raise ValueError("LLM did not return a JSON object")
    return data


_cloud_transport = None  # test seam: httpx.MockTransport, mirrors CloudApiEngine


_RETRY_AFTER_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)
_MAX_429_RETRIES = 6


def _retry_delay_s(resp) -> float:
    """Cooldown from a 429: Retry-After header, or Groq's 'try again in Xs'
    message text; conservative default otherwise."""
    header = resp.headers.get("retry-after", "")
    if header.replace(".", "", 1).isdigit():
        return float(header)
    m = _RETRY_AFTER_RE.search(resp.text)
    return float(m.group(1)) if m else 10.0


def _cloud_chat_json(settings, prompt: str) -> dict:
    """One JSON-mode call against the OpenAI-compatible chat-completions API
    (Groq by default — same CHATBOT_* config the cloud chatbot uses).
    Free-tier rate limits (429) are waited out and retried, so a chunked
    conversion completes slowly instead of failing. Connection/API failures
    raise LlmUnavailableError; a bad payload raises ValueError (caller
    retries)."""
    import httpx  # lazy, mirrors chatbot_service

    try:
        with httpx.Client(
            transport=_cloud_transport, timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            for _ in range(_MAX_429_RETRIES):
                resp = client.post(
                    f"{settings.chatbot_api_base.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.chatbot_api_key}"},
                    json={
                        "model": settings.chatbot_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                        # generous: reasoning models (gpt-oss-*) spend
                        # completion tokens on reasoning before the JSON
                        "max_tokens": 4096,
                    },
                )
                if resp.status_code != 429:
                    break
                time.sleep(min(_retry_delay_s(resp) + 0.5, 30.0))
    except httpx.HTTPError as exc:
        raise LlmUnavailableError(f"cloud LLM API not reachable: {exc}")
    if resp.status_code != 200:
        raise LlmUnavailableError(
            f"cloud LLM API returned {resp.status_code}: {resp.text[:300]}"
        )
    choices = resp.json().get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content") or ""
    data = json.loads(content)  # ValueError on garbage/empty
    if not isinstance(data, dict):
        raise ValueError("LLM did not return a JSON object")
    return data


def _pick_backend(settings):
    """Choose the JSON-chat backend: (chat callable, model name, backend tag).

    Local Ollama wins when enabled and reachable (the pilot path). Otherwise
    fall back to the cloud API when CHATBOT_API_KEY is set — this also makes
    PDF conversion work on cloud/demo deployments where ENABLE_LLM=0."""
    if settings.enable_llm:
        try:
            import ollama

            ollama.list()  # cheap reachability probe
        except Exception:
            pass  # fall through to the cloud backend (or the error below)
        else:
            model = _resolve_model()
            return (lambda p: _ollama_chat_json(model, p)), model, "ollama"
    if settings.chatbot_api_key:
        return (
            (lambda p: _cloud_chat_json(settings, p)),
            settings.chatbot_model,
            "cloud",
        )
    raise LlmUnavailableError(
        "no LLM backend: Ollama is "
        + ("not reachable" if settings.enable_llm else "disabled (ENABLE_LLM=0)")
        + " and CHATBOT_API_KEY is not set for the cloud fallback"
    )


def _call_with_retry(chat, prompt: str) -> dict | None:
    """Retry-once on unparseable output; None after the second failure."""
    for _ in range(2):
        try:
            return chat(prompt)
        except (ValueError, KeyError, TypeError):
            continue
    return None


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:max_len].strip("_") or "untitled"


def assemble_tutorial(metadata: dict, chunks: list[dict], existing_ids: set,
                      source_name: str = "", model: str = "") -> dict:
    """Deterministic assembly: everything the validator ERRORs on is built
    here, never trusted from the LLM."""
    title = str(metadata.get("title", "")).strip() or "Untitled tutorial"
    problem = str(metadata.get("problem", "")).strip()

    counters = {prefix: 0 for prefix in APP_PREFIX.values()}
    seen_ids: set = set(RESERVED_STEP_IDS)
    sections = []
    apps_in_order: list[str] = []

    for i, chunk in enumerate(chunks, start=1):
        steps_out = []
        for raw_step in (chunk.get("steps") or [])[:MAX_STEPS_PER_CHUNK]:
            if not isinstance(raw_step, dict):
                continue
            s_title = str(raw_step.get("title", "")).strip()
            s_desc = str(raw_step.get("description", "")).strip()
            if not s_title or not s_desc:
                continue
            app = str(raw_step.get("app", "")).strip().lower()
            if app not in APPS:
                app = "mechanical"
            prefix = APP_PREFIX[app]
            counters[prefix] += 1
            step_id = f"{prefix}_{counters[prefix]:02d}_{_slugify(s_title, 24)}"
            while step_id in seen_ids:
                step_id += "_b"
            seen_ids.add(step_id)
            hints = [str(h).strip() for h in (raw_step.get("hints") or [])
                     if str(h).strip()][:2]
            steps_out.append(
                {
                    "step_id": step_id,
                    "app": app,
                    "title": s_title,
                    "description": s_desc,
                    "highlight": "none",
                    "verify": {"type": "manual", "prompt": f"Did you complete: {s_title}?"},
                    "hints": hints,
                }
            )
            if app not in apps_in_order:
                apps_in_order.append(app)
        if steps_out:
            section_title = str(chunk.get("section_title", "")).strip() or f"Part {i}"
            # section app = most common app among its steps
            app_counts: dict = {}
            for st in steps_out:
                app_counts[st["app"]] = app_counts.get(st["app"], 0) + 1
            section_app = max(app_counts, key=app_counts.get)
            sections.append({"section": section_title, "app": section_app, "steps": steps_out})

    tutorial_id = _slugify(title)
    if tutorial_id in existing_ids:
        n = 2
        while f"{tutorial_id}_{n}" in existing_ids:
            n += 1
        tutorial_id = f"{tutorial_id}_{n}"

    return {
        "tutorial_id": tutorial_id,
        "version": 1,
        "title": title,
        "problem": problem,
        "apps": apps_in_order or ["mechanical"],
        "_notes": {
            "source": f"generated from PDF '{source_name}' by {model} on "
                      f"{time.strftime('%Y-%m-%d')}",
            "review": "Auto-generated draft — verify every step against the PDF "
                      "before publishing. All steps use manual verification and no "
                      "highlighting; add selectors/source_images by editing this JSON.",
        },
        "sections": sections,
    }


def convert_pdf(raw: bytes, filename: str, settings, existing_ids: set) -> tuple[dict, dict]:
    """PDF bytes -> (tutorial dict, generation info)."""
    chat, model, backend = _pick_backend(settings)
    pages = _extract_pages(raw)

    metadata = _call_with_retry(
        chat, METADATA_PROMPT.format(text="\n".join(pages[:PAGES_PER_CHUNK])[:CHUNK_CHAR_CAP])
    )
    if metadata is None:
        # survivable: name the tutorial after the file, leave problem blank
        metadata = {"title": _slugify(filename.rsplit(".", 1)[0], 40).replace("_", " ").title(),
                    "problem": ""}

    chunks = []
    skipped = 0
    chunk_ranges = [
        (i, min(i + PAGES_PER_CHUNK, len(pages)))
        for i in range(0, len(pages), PAGES_PER_CHUNK)
    ]
    for a, b in chunk_ranges:
        text = "\n".join(pages[a:b])[:CHUNK_CHAR_CAP]
        if not text.strip():
            continue
        result = _call_with_retry(
            chat,
            STEPS_PROMPT.format(max_steps=MAX_STEPS_PER_CHUNK, a=a + 1, b=b, text=text),
        )
        if result is None:
            skipped += 1
            continue
        chunks.append(result)

    tutorial = assemble_tutorial(metadata, chunks, existing_ids,
                                 source_name=filename, model=model)
    if not tutorial["sections"]:
        raise GenerationFailedError(
            "the model could not extract any tutorial steps from this PDF"
        )
    gen_info = {
        "model": model,
        "backend": backend,
        "pages": len(pages),
        "chunks": len(chunk_ranges),
        "skipped_chunks": skipped,
    }
    return tutorial, gen_info

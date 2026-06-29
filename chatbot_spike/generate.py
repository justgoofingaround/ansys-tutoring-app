"""
LLM generator + citation tracker -- architecture doc Section 8.1's final
pipeline stage. Takes retrieved chunks + the student's question (+ optional
tutorial/step context, mirroring the doc's "Context fetcher" concept) and
asks a local Ollama model for an answer.

CITATION HANDLING IS DETERMINISTIC, NOT LLM-TRUSTED: the prompt instructs the
model to mark claims with [1], [2]... matching the numbered context list,
but an LLM can mis-cite or omit citations. format_answer() always appends
the FULL list of sources actually retrieved and used as context underneath
the model's answer, regardless of whether the model's inline [n] markers are
perfect -- so "every answer cites its source" (architecture doc Section 8.2,
an Ansys Academic license requirement, not just a nice-to-have) holds even
if the model's inline citation behavior is imperfect.
"""

import ollama

from config import MAX_RESPONSE_TOKENS, OLLAMA_MODEL

SYSTEM_PROMPT = """You are Compass, an assistant embedded in a tutoring tool for NYU's \
ME-UY 4214 Finite Element Analysis course, helping students use Ansys Mechanical. If asked \
your name, say you're Compass.

Rules:
1. Answer ONLY using the numbered context passages provided. If the context doesn't \
contain the answer, say so plainly instead of guessing.
2. PARAPHRASE the documentation in your own words. Never quote more than a short \
phrase verbatim -- this is a licensing requirement (Ansys Academic license), not a style preference.
3. Mark every factual claim with the bracketed number(s) of the context passage(s) \
it came from, like [1] or [2][3].
4. BE BRIEF -- a student is mid-tutorial waiting for an answer. Default to 2-4 short \
sentences or a short list of 2-3 steps. Only go longer if the question explicitly asks \
for a full walkthrough or a comparison of multiple methods.
5. If `tutorial context` is provided below, tailor the answer to that step rather \
than giving a fully generic answer -- don't re-explain things the student has clearly \
already done (e.g. don't say "first create a Static Structural analysis" if the context \
says they're already several steps past that)."""


def _build_user_message(question, chunks, tutorial_context=None):
    context_block = "\n\n".join(
        f"[{i + 1}] (source: {c['metadata']['citation']})\n{c['text']}"
        for i, c in enumerate(chunks)
    )
    parts = []
    if tutorial_context:
        parts.append(f"Tutorial context: {tutorial_context}")
    parts.append(f"Context passages:\n\n{context_block}")
    parts.append(f"Student question: {question}")
    return "\n\n".join(parts)


def _sources_from_chunks(chunks):
    """De-duplicated, ordered list of citation strings for every chunk
    actually used as context -- see module docstring for why this is always
    appended regardless of the model's own inline-citation behavior."""
    seen = set()
    sources = []
    for c in chunks:
        citation = c["metadata"]["citation"]
        if citation not in seen:
            seen.add(citation)
            sources.append(citation)
    return sources


def generate_answer(question, chunks, tutorial_context=None, model=OLLAMA_MODEL):
    """Non-streaming: blocks until the full answer is generated, then
    returns (answer_text, sources) in one shot. Used by query.py (a CLI has
    no "show partial output as it arrives" UI to update anyway). See
    stream_answer() for the token-by-token version the GUI uses instead."""
    if not chunks:
        return ("I couldn't find anything in the indexed Ansys documentation "
                "relevant to that question.", [])
    response = ollama.chat(model=model, messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(question, chunks, tutorial_context)},
    ], options={"num_predict": MAX_RESPONSE_TOKENS})
    answer = response["message"]["content"]
    return answer, _sources_from_chunks(chunks)


def stream_answer(question, chunks, tutorial_context=None, model=OLLAMA_MODEL, on_token=None):
    """Streaming version: calls `on_token(piece)` as each piece of the
    answer arrives from Ollama, for a UI that wants to show the response
    growing in real time instead of a frozen "Thinking..." for the entire
    generation -- this is a PERCEIVED-speed fix, not an actual-latency fix
    (the model still takes the same total time to generate the full answer;
    seeing it appear immediately just makes the wait feel much shorter,
    confirmed as the standard UX pattern for chat interfaces for exactly
    this reason). Returns (full_answer_text, sources) once streaming ends,
    same contract as generate_answer()."""
    if not chunks:
        msg = ("I couldn't find anything in the indexed Ansys documentation "
               "relevant to that question.")
        if on_token:
            on_token(msg)
        return msg, []
    stream = ollama.chat(model=model, messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(question, chunks, tutorial_context)},
    ], options={"num_predict": MAX_RESPONSE_TOKENS}, stream=True)
    pieces = []
    for part in stream:
        piece = part["message"]["content"]
        pieces.append(piece)
        if piece and on_token:
            on_token(piece)
    return "".join(pieces), _sources_from_chunks(chunks)


def format_answer(answer, sources):
    lines = [answer, "", "Sources:"]
    lines += [f"  - {s}" for s in sources]
    return "\n".join(lines)

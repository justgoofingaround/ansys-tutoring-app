"""
Token-aware chunker, separate from parsing.py (which knows file formats) and
ingest.py (which knows about embeddings/storage) -- this module only knows
how to turn [(text, label), ...] into fixed-size, overlapping token windows.

Token-COUNT chunking (not character or word count) is what actually makes
"300-500 tokens" (architecture doc Section 8.1) a meaningful, enforceable
target -- word/character counts are a rough proxy at best across documents
with very different prose density (a command reference's tight syntax blocks
vs a tutorial's narrative prose).
"""

import tiktoken

from config import CHUNK_TOKENS, OVERLAP_TOKENS

_ENC = tiktoken.get_encoding("cl100k_base")  # general-purpose tokenizer, used
                                              # only to size chunks consistently
                                              # -- not tied to any specific
                                              # embedding/LLM model's own
                                              # tokenizer, which doesn't matter
                                              # for this purpose


def chunk_document(pages, chunk_tokens=CHUNK_TOKENS, overlap_tokens=OVERLAP_TOKENS):
    """pages: [(text, label), ...] from parsing.parse_document(), in document
    order. Returns [{"text": str, "label_start": ..., "label_end": ...}, ...]
    -- a sliding window over the WHOLE document's token stream (not chunked
    independently per page/section), so a chunk can span a page/section
    boundary when content naturally does, while still recording which
    page(s)/section the window actually touched for citation."""
    # Flatten to one token stream, remembering which (page/section) label
    # each token came from, with a literal space between pages/sections so
    # words at a boundary don't get fused together.
    tokens = []
    token_labels = []
    for text, label in pages:
        text_tokens = _ENC.encode(text)
        tokens.extend(text_tokens)
        token_labels.extend([label] * len(text_tokens))
        sep = _ENC.encode(" ")
        tokens.extend(sep)
        token_labels.extend([label] * len(sep))

    if not tokens:
        return []

    chunks = []
    step = max(1, chunk_tokens - overlap_tokens)
    for start in range(0, len(tokens), step):
        end = min(start + chunk_tokens, len(tokens))
        window = tokens[start:end]
        if not window:
            break
        text = _ENC.decode(window).strip()
        if text:
            chunks.append({
                "text": text,
                "label_start": token_labels[start],
                "label_end": token_labels[end - 1],
            })
        if end == len(tokens):
            break
    return chunks


def format_citation(filename, label_start, label_end):
    """Human-readable citation string. Pages are ints (PDF); sections are
    strings (HTML heading text) -- see parsing.py."""
    if isinstance(label_start, int):
        if label_start == label_end:
            return f"{filename}, p. {label_start}"
        return f"{filename}, pp. {label_start}-{label_end}"
    if label_start == label_end:
        return f"{filename}, “{label_start}”"
    return f"{filename}, “{label_start}”–“{label_end}”"

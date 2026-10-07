"""
CLI for the Ansys Help Chatbot spike. Ties retrieve.py + generate.py
together -- this is the "per-query flow" half of architecture doc Section
8.1 (the other half, one-time doc ingestion, is ingest.py).

RUN:
  python query.py "How do I refine the mesh on a face?"
  python query.py "How do I refine the mesh on a face?" --tutorial-context "Tut-1, step 9 (Generate the mesh)"
  python query.py "..." --no-hybrid     (semantic search only, for comparison)
  python query.py "..." --show-chunks   (print the raw retrieved chunks before the answer)
"""

import argparse
import sys

# Ansys docs are full of characters (->, degree signs, superscripts) that
# Windows' default console codepage (cp1252) can't encode -- confirmed live,
# printing a chunk containing U+2192 crashed mid-run with UnicodeEncodeError.
# Force UTF-8 with a safe fallback instead of failing on the next exotic
# character some other document happens to contain.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import CHROMA_DIR, MANIFEST_PATH
from generate import format_answer, generate_answer
from retrieve import retrieve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--tutorial-context", default=None,
                     help='e.g. "Tut-1, step 9 (Generate the mesh)" -- mirrors the '
                          "architecture doc's Context fetcher; in the real module this "
                          "comes from the Student Interaction Track App automatically.")
    ap.add_argument("--no-hybrid", action="store_true", help="semantic search only")
    ap.add_argument("--show-chunks", action="store_true", help="print retrieved chunks first")
    ap.add_argument("--k", type=int, default=None, help="override TOP_K")
    args = ap.parse_args()

    if not MANIFEST_PATH.exists() or not CHROMA_DIR.exists():
        sys.exit("No index found -- run `python ingest.py` first.")

    kwargs = {"hybrid": not args.no_hybrid}
    if args.k:
        kwargs["top_k"] = args.k
    chunks = retrieve(args.question, **kwargs)

    if args.show_chunks:
        print(f"--- {len(chunks)} retrieved chunk(s) ---")
        for i, c in enumerate(chunks, 1):
            print(f"[{i}] {c['metadata']['citation']}")
            print(c["text"][:300].replace("\n", " ") + ("..." if len(c["text"]) > 300 else ""))
            print()

    answer, sources = generate_answer(args.question, chunks, tutorial_context=args.tutorial_context)
    print(format_answer(answer, sources))


if __name__ == "__main__":
    main()

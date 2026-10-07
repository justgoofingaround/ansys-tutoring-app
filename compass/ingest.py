"""
Doc indexer (one-time / incremental setup) -- architecture doc Section 8.1's
"Doc indexer" sub-component. Parses each file in config.RELEVANT_DOCS,
chunks it, embeds the chunks, and stores them in ChromaDB (semantic search)
AND a parallel BM25 index (keyword search) -- see retrieve.py for why both.

INCREMENTAL BY DESIGN: re-running this only (re)processes files that are new
or changed since the last run (tracked in config.MANIFEST_PATH by mtime+size).
With a 342 MB curated corpus and a CPU-only sentence-transformers model,
embedding everything from scratch takes real minutes; without this, every
unrelated code change to this spike would force a full re-embed.

RUN: python ingest.py            (process whatever's new since last run)
     python ingest.py --rebuild  (wipe everything and reprocess from scratch
                                   -- needed after changing CHUNK_TOKENS/
                                   OVERLAP_TOKENS/EMBEDDING_MODEL, since
                                   existing chunks were sized/embedded under
                                   the old params)
"""

import argparse
import json
import pickle
import sys

# See query.py for why -- Ansys docs contain characters Windows' default
# console codepage can't encode.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chromadb
from sentence_transformers import SentenceTransformer

from chunking import chunk_document, format_citation
from config import (
    BM25_PATH, CHROMA_DIR, COLLECTION_NAME, DATA_DIR, DOCS_DIR,
    EMBEDDING_MODEL, MANIFEST_PATH, RELEVANT_DOCS,
)
from parsing import parse_document


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_bm25_corpus():
    """Returns the full list of {"id", "text", "metadata"} chunk records
    accumulated across all previously-ingested files -- BM25 (unlike Chroma)
    has no incremental-update API worth using here, so it's rebuilt from this
    complete record set at the end of every ingest run instead."""
    if BM25_PATH.exists():
        with open(BM25_PATH, "rb") as f:
            return pickle.load(f)["chunks"]
    return []


def save_bm25_index(chunks):
    from rank_bm25 import BM25Okapi
    tokenized = [c["text"].lower().split() for c in chunks]
    bm25 = BM25Okapi(tokenized)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(BM25_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": chunks}, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                     help="wipe the manifest/index and reprocess every file from scratch")
    args = ap.parse_args()

    missing = [d for d in RELEVANT_DOCS if not (DOCS_DIR / d).exists()]
    if missing:
        sys.exit(f"Missing documents in {DOCS_DIR}: {missing}")

    manifest = {} if args.rebuild else load_manifest()
    bm25_chunks = [] if args.rebuild else load_bm25_corpus()
    bm25_chunks = [c for c in bm25_chunks if c["metadata"]["source"] in RELEVANT_DOCS]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if args.rebuild:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
    collection = client.get_or_create_collection(COLLECTION_NAME)

    print(f"Loading embedding model {EMBEDDING_MODEL!r}...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    to_process = []
    for filename in RELEVANT_DOCS:
        path = DOCS_DIR / filename
        stat = path.stat()
        prev = manifest.get(filename)
        if prev and prev["mtime"] == stat.st_mtime and prev["size"] == stat.st_size:
            continue
        to_process.append((filename, path, stat))

    if not to_process:
        print(f"Nothing new to index. {len(RELEVANT_DOCS)} document(s) already up to date.")
        return

    print(f"Indexing {len(to_process)} new/changed document(s) "
          f"(skipping {len(RELEVANT_DOCS) - len(to_process)} already up to date)...")

    for filename, path, stat in to_process:
        print(f"  {filename} ...", end=" ", flush=True)
        # Drop this file's old chunks first (re-processing a CHANGED file
        # shouldn't leave stale chunks from its previous version behind).
        bm25_chunks = [c for c in bm25_chunks if c["metadata"]["source"] != filename]
        try:
            old_ids = collection.get(where={"source": filename})["ids"]
            if old_ids:
                collection.delete(ids=old_ids)
        except Exception:
            pass

        pages = parse_document(path)
        chunks = chunk_document(pages)
        if not chunks:
            print("0 chunks (no extractable text?)")
            manifest[filename] = {"mtime": stat.st_mtime, "size": stat.st_size, "n_chunks": 0}
            continue

        texts = [c["text"] for c in chunks]
        embeddings = model.encode(texts, show_progress_bar=False, batch_size=32).tolist()
        ids, metadatas = [], []
        for i, c in enumerate(chunks):
            citation = format_citation(filename, c["label_start"], c["label_end"])
            meta = {"source": filename, "citation": citation,
                     "label_start": str(c["label_start"]), "label_end": str(c["label_end"])}
            ids.append(f"{filename}::{i}")
            metadatas.append(meta)
            bm25_chunks.append({"id": ids[-1], "text": c["text"], "metadata": meta})

        collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        manifest[filename] = {"mtime": stat.st_mtime, "size": stat.st_size, "n_chunks": len(chunks)}
        print(f"{len(chunks)} chunks")

    save_manifest(manifest)
    print("Rebuilding BM25 keyword index...")
    save_bm25_index(bm25_chunks)
    print(f"Done. {sum(m['n_chunks'] for m in manifest.values())} total chunks "
          f"across {len(manifest)} document(s).")


if __name__ == "__main__":
    main()

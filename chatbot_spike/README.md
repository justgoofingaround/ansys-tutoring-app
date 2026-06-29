# Compass — Ansys Help Chatbot spike

Phase 0 spike for the **Ansys Help Chatbot** module (architecture doc Section 8),
named **Compass** in the student-facing UI (`guide_tut1.py`'s "💬 Ask Compass"
button) — proves the RAG (retrieval-augmented generation) pipeline works end-to-end
against real Ansys Mechanical documentation, fully local, before the real module
gets built. Same "de-risk first" approach as `spikes/` for the Student Interaction
Track App, just a separate module with its own spike directory (see the Jira
ticket for the full scope/risks this is meant to surface).

## What it does

1. **`ingest.py`** — parses a curated set of Ansys PDFs/HTML (see `config.RELEVANT_DOCS`),
   chunks them (~400 tokens, 60-token overlap), embeds with `sentence-transformers`
   (`all-MiniLM-L6-v2`), and stores them in a local **ChromaDB** vector store + a
   **BM25** keyword index. Incremental — re-running only processes new/changed files.
2. **`retrieve.py`** — hybrid search: runs semantic (vector) search and BM25
   (keyword) search independently, then fuses the two rankings with **Reciprocal
   Rank Fusion**. See the module docstring for why hybrid beats semantic-only on
   documentation full of exact command names/menu paths.
3. **`generate.py`** — sends the retrieved chunks + question to a local **Ollama**
   model, with a system prompt that requires paraphrasing (not verbatim quoting —
   an Ansys Academic license requirement) and inline citation markers. The final
   answer always lists every source actually used, independent of whether the
   model's own inline citations are perfect.
4. **`query.py`** — CLI tying retrieval + generation together.

## Setup

```
pip install -r requirements.txt
```

You also need [Ollama](https://ollama.com) installed and at least one model pulled
(`ollama pull gemma3:4b`, or whatever you set `OLLAMA_MODEL` to in `config.py`).

`config.DOCS_DIR` points at a real Ansys documentation folder (set the `ANSYS_DOCS_DIR`
environment variable to your own path — it's machine-specific and not checked into git)
and `config.RELEVANT_DOCS` curates ~19 Mechanical/Workbench/Meshing/DesignModeler-relevant
PDFs out of the full 284-document, 3.2 GB Ansys 2026 R1 doc set — indexing the whole
corpus would take hours and dilute retrieval with irrelevant Fluent/LS-DYNA/Rocky/Speos
content for a Mechanical-only course. Add filenames to `RELEVANT_DOCS` to widen the corpus.

**`DOCS_DIR` is only needed if you're building or extending the index.** If you already
have a pre-built `data/` folder (ChromaDB + `bm25_index.pkl`, ~227 MB — see "Distributing
the index" below), you can skip straight to `python query.py "..."` with no PDFs at all,
since the built index carries the actual extracted text, not just embeddings.

## Distributing the index

`data/` is gitignored on purpose: it's ~227 MB, and one file inside it
(`chroma_db/chroma.sqlite3`, ~165 MB) exceeds GitHub's 100 MB hard per-file limit, so it
can't be pushed as a normal commit at all (it would need Git LFS). Until that's set up,
getting this running on another machine means either:
- copying the `data/` folder there directly (zip it, shared drive, etc.), or
- running `ingest.py` fresh on that machine, with `ANSYS_DOCS_DIR` pointed at a local copy
  of the source PDFs (~340 MB for the curated subset).

## Run it

```
python ingest.py                  # build/update the index (first run takes a few minutes)
python query.py "How do I refine the mesh on a face?"
python query.py "..." --tutorial-context "Tut-1, step 9 (Generate the mesh)"
python query.py "..." --show-chunks     # see what was actually retrieved
python query.py "..." --no-hybrid       # semantic search only, for comparison
```

## What this spike does NOT cover (real-module work, not this ticket)

- Live integration with the Student Interaction Track App's actual model state
  (the `--tutorial-context` flag is a stand-in for the architecture doc's
  "Context fetcher" sub-component, which in the real module queries the
  student app automatically).
- The REST API, consent-screen UI, query logging/encryption (FERPA requirements
  in architecture doc Section 8.2) — this spike runs entirely offline/local with
  no logging at all.
- Re-ranking with a cross-encoder (a further retrieval-quality optimization beyond
  hybrid search) — worth trying if hybrid search alone isn't precise enough once
  tested against real student questions.

## Findings (fill in as you test)

- **Hybrid vs. semantic-only retrieval, confirmed on a real query** ("How do I refine
  the mesh on a face?"): hybrid search surfaced pages literally titled "Refinement
  controls" and "Refine Surface Mesh" (`ANSYS_Meshing_Users_Guide.pdf` pp. 218/323).
  Semantic-only search on the same query drifted toward the adjacent-but-distinct
  "Inflation" meshing feature and pulled in less relevant `SpaceClaim_Documentation.pdf`
  (facet auto-fix) and defeature-tolerance content instead. The keyword (BM25) half of
  the hybrid search is doing real work here, not just redundant with semantic search.
- **Boilerplate noise**: every page's repeated copyright/legal footer ("Contains
  proprietary and confidential information of Synopsys, Inc., ANSYS, Inc....") gets
  chunked like any other text and occasionally gets retrieved as a real hit (confirmed
  live — one query's top-5 included a page that was almost entirely this boilerplate
  plus an unrelated IP-collection FAQ). Worth stripping this footer pattern out during
  parsing before chunking, rather than relying on retrieval/generation to ignore it.
- **Filenames are not a reliable proxy for content** — confirmed live, see config.py's
  note on `DM_modelling.pdf` (sounded like generic DesignModeler usage, was actually
  AQWA-specific). Spot-check any new addition to `RELEVANT_DOCS` by actually parsing it.
- Retrieval quality against realistic student questions: (continue testing)
- Local LLM (model: see `config.OLLAMA_MODEL`) latency per query:
- Citation accuracy (does the model's [n] usage actually match what supports the claim?):
- Anything that needed re-tuning (chunk size, TOP_K, RRF_K, etc.):

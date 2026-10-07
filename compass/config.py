"""
Config for the Ansys Help Chatbot spike -- see README.md for what this spike
proves and architecture doc Section 8 ("Module: Ansys Help Chatbot") for the
real module this de-risks.

DOCS_DIR points at the real Ansys 2026 R1 (v261) documentation set. That
folder has 284 PDFs (~3.2 GB) covering EVERY Ansys product (Fluent, CFX,
LS-DYNA, Rocky, Speos, ...), not just Mechanical. ME-UY 4214 is FEA/Mechanical
only (CLAUDE.md: "Fall 2026 ships with Mechanical only"), so RELEVANT_DOCS
curates a Mechanical/Workbench/Meshing/DesignModeler-relevant subset (~340 MB)
instead of indexing the entire corpus -- indexing everything would take hours
and would dilute retrieval with irrelevant CFD/explicit-dynamics/sound/optics
content for a course that never touches those products. Add filenames here
(they must exist in DOCS_DIR) to widen the corpus; nothing else needs to change.

NOTE: filenames alone are an unreliable guide to content -- confirmed live,
"DM_modelling.pdf" sounds like generic DesignModeler usage but is actually an
AQWA-specific (marine hydrodynamics) modelling guide, irrelevant to this
course, and was removed after inspecting its actual parsed text. Spot-check
new additions the same way rather than trusting the filename.

DOCS_DIR is only read by ingest.py (building/rebuilding the index) -- never
by retrieve.py/generate.py/query.py at question-answering time, since the
built index in DATA_DIR already carries the real extracted chunk text. So a
machine that only has the pre-built index (no PDFs at all) can still answer
questions; DOCS_DIR only matters to whoever re-runs or extends the index.
It's a machine-specific path (the original Ansys doc set isn't checked into
git, see DATA_DIR below), so it's read from the ANSYS_DOCS_DIR environment
variable with this hardcoded path as a fallback default for this machine --
set that env var instead of editing this file on a different machine.
"""

import os
from pathlib import Path

DOCS_DIR = Path(os.environ.get(
    "ANSYS_DOCS_DIR", r"D:\tutoring app docs\chatbot data\ProductDocPDF\v261"))

RELEVANT_DOCS = [
    "Ansys_Mechanical_Users_Guide.pdf",
    "ANSYS_Mechanical_Tutorials_2026_R1.pdf",
    "Mechanical_Object_Reference.pdf",
    "Mechanical_Add-ons_Guide.pdf",
    "Ansys_Scripting_in_Mechanical_Guide.pdf",
    "ACT_Customization_Guide_for_Mechanical.pdf",
    "ACT_Customization_Guide_for_Workbench.pdf",
    "Workbench_Users_Guide.pdf",
    "Workbench_Scripting_Guide.pdf",
    "ANSYS_Meshing_Users_Guide.pdf",
    "ANSYS_Meshing_Tutorial_Guide_2026_R1.pdf",
    "Engineering_Data_Users_Guide.pdf",
    "DesignModeler_Users_Guide.pdf",
    "SpaceClaim_Documentation.pdf",
    "ANSYS_Mechanical_APDL_Structural_Analysis_Guide.pdf",
    "ANSYS_Mechanical_APDL_Basic_Analysis_Guide.pdf",
    "ANSYS_Mechanical_APDL_Introductory_Tutorials.pdf",
    "Ansys_Workbench_Verification_Manual.pdf",
]

# Where this spike's generated artifacts live (gitignored -- regenerable from
# DOCS_DIR + RELEVANT_DOCS, and the vector/BM25 indexes are large binary data
# that don't belong in git).
DATA_DIR = Path(__file__).resolve().parent / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
BM25_PATH = DATA_DIR / "bm25_index.pkl"
MANIFEST_PATH = DATA_DIR / "index_manifest.json"

COLLECTION_NAME = "ansys_mechanical_docs"

# Chunking. Architecture doc Section 8.1 specifies "300-500 tokens" per chunk;
# OVERLAP_TOKENS keeps a sentence or two of continuity across chunk
# boundaries so an answer-relevant sentence split across two chunks doesn't
# get lost from both.
CHUNK_TOKENS = 400
OVERLAP_TOKENS = 60

# Embeddings -- exact model named in architecture doc Section 8.1.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Retrieval. Architecture doc Section 8.1: "top-K most relevant chunks
# (typically K = 5-8)". HYBRID_FETCH_K is how many candidates EACH of
# semantic search and BM25 fetch independently before Reciprocal Rank Fusion
# narrows down to TOP_K -- needs to be larger than TOP_K so RRF has enough
# candidates from both rankings to actually re-rank, not just concatenate.
TOP_K = 6
HYBRID_FETCH_K = 20
RRF_K = 60  # standard RRF damping constant (Cormack et al.) -- de-emphasizes
            # rank position differences far down either ranked list

# Local LLM via Ollama. The architecture doc names Llama 3 or Qwen 2.5; this
# machine already has gemma3:4b pulled (`ollama list`), so default to that to
# avoid a multi-GB download just to run the spike. Swap via --model.
OLLAMA_MODEL = "gemma3:4b"

# Caps generation length (Ollama's num_predict). Confirmed live: an
# unbounded answer to a simple "how do I refine the mesh" question ran to 5
# detailed numbered points and took a long time to fully generate -- a
# student mid-tutorial wants the next concrete step, not an exhaustive
# essay, and shorter generations are also just faster (LLM throughput is
# roughly constant per output token, so fewer tokens -> less wait).
MAX_RESPONSE_TOKENS = 220

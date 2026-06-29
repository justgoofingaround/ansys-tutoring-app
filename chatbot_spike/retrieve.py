"""
Retriever -- architecture doc Section 8.1's "Retriever" sub-component, with
one optimization beyond the documented spec: HYBRID search (semantic +
keyword), not semantic-only.

WHY HYBRID: Ansys documentation is full of exact, jargon-heavy strings a
student's question will often quote verbatim -- command names ("ESEL",
"SOLVE"), exact menu paths ("Insert > Deformation > Directional"), error
codes. Pure semantic search (cosine similarity over sentence embeddings)
sometimes ranks a paraphrased-but-less-relevant chunk above the chunk that
contains the EXACT term, because embedding models compress meaning and can
under-weight a single rare token. BM25 (keyword/term-frequency search) is
the opposite failure mode -- great at exact terms, poor at paraphrase ("how
do I make the mesh finer" vs. documentation's "mesh refinement"). Running
both and fusing the rankings (Reciprocal Rank Fusion) covers both failure
modes instead of picking one.
"""

import pickle

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    BM25_PATH, CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL,
    HYBRID_FETCH_K, RRF_K, TOP_K,
)

_model = None
_collection = None
_bm25 = None
_bm25_chunks = None


def _lazy_init():
    global _model, _collection, _bm25, _bm25_chunks
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(COLLECTION_NAME)
        if BM25_PATH.exists():
            with open(BM25_PATH, "rb") as f:
                data = pickle.load(f)
            _bm25, _bm25_chunks = data["bm25"], data["chunks"]
        else:
            _bm25, _bm25_chunks = None, []


def _semantic_search(query, k):
    embedding = _model.encode([query]).tolist()
    res = _collection.query(query_embeddings=embedding, n_results=k)
    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(ids, docs, metas)]


def _keyword_search(query, k):
    if _bm25 is None or not _bm25_chunks:
        return []
    scores = _bm25.get_scores(query.lower().split())
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [_bm25_chunks[i] for i in ranked if scores[i] > 0]


def _reciprocal_rank_fusion(rankings, k=RRF_K):
    """rankings: list of ranked chunk-lists (each already sorted best-first).
    RRF score for a chunk = sum over rankings of 1/(k + rank_in_that_ranking).
    A chunk that ranks well in BOTH semantic and keyword search rises to the
    top; a chunk that only one method found still gets a chance instead of
    being dropped (unlike taking the simple intersection)."""
    scores = {}
    chunk_by_id = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            scores[chunk["id"]] = scores.get(chunk["id"], 0.0) + 1.0 / (k + rank + 1)
            chunk_by_id[chunk["id"]] = chunk
    fused = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [chunk_by_id[cid] for cid, _ in fused]


def retrieve(query, top_k=TOP_K, hybrid=True):
    """Returns up to top_k {"id", "text", "metadata"} chunks for `query`,
    best-first. hybrid=False uses semantic search alone (useful for A/B
    comparison while tuning, see query.py's --no-hybrid flag)."""
    _lazy_init()
    if not hybrid:
        return _semantic_search(query, top_k)
    semantic = _semantic_search(query, HYBRID_FETCH_K)
    keyword = _keyword_search(query, HYBRID_FETCH_K)
    fused = _reciprocal_rank_fusion([semantic, keyword])
    return fused[:top_k]

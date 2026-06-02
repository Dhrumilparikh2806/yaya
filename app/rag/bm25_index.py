"""
BM25 sparse retrieval index.

The index is built from all documents currently in ChromaDB using rank_bm25
(BM25Okapi) and stored in Redis as a pickled blob (TTL = 24 hours).

Lifecycle:
  - build_bm25()    — called when the cache is cold (after first query post-ingest).
  - invalidate_bm25() — called by process_file after every successful indexing so
                        the next query rebuilds from fresh ChromaDB data.
  - load_bm25()     — returns None on cache miss; caller falls back to build_bm25().
  - search_bm25()   — keyword search; scores are max-normalised to [0, 1] so they
                      can be compared with vector scores inside RRF merge.

Note: _tokenize() uses whitespace splitting only.  Punctuation attached to words
(e.g. "company.") is treated as part of the token.  This is intentional — it
keeps the tokenizer fast and avoids NLTK/spaCy as a dependency.
"""

import pickle

from app.observability.logging import get_logger

log = get_logger()

_REDIS_KEY = "geminirag:bm25_index"
_TTL = 86400  # 24 hours


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def build_bm25(collection, settings) -> dict:
    """Build BM25 index from all chunks in ChromaDB and cache in Redis."""
    from rank_bm25 import BM25Okapi
    import redis as redis_sdk

    result = collection.get(include=["documents", "metadatas"])
    docs = result["documents"] or []
    metas = result["metadatas"] or []
    ids = result["ids"] or []

    tokenized = [_tokenize(d) for d in docs] if docs else [[""]]
    bm25 = BM25Okapi(tokenized)
    index_data = {"bm25": bm25, "docs": docs, "metas": metas, "ids": ids}

    try:
        rc = redis_sdk.from_url(settings.REDIS_URL)
        rc.set(_REDIS_KEY, pickle.dumps(index_data), ex=_TTL)
        log.info("bm25_index_built", chunk_count=len(docs))
    except Exception as exc:
        log.warning("bm25_cache_write_failed", error=str(exc))

    return index_data


def load_bm25(settings) -> dict | None:
    """Load BM25 index from Redis. Returns None if not cached."""
    import redis as redis_sdk

    try:
        rc = redis_sdk.from_url(settings.REDIS_URL)
        cached = rc.get(_REDIS_KEY)
        if cached:
            return pickle.loads(cached)
    except Exception as exc:
        log.warning("bm25_cache_read_failed", error=str(exc))
    return None


def invalidate_bm25(settings) -> None:
    """Invalidate BM25 cache — call after adding new chunks to ChromaDB."""
    import redis as redis_sdk

    try:
        rc = redis_sdk.from_url(settings.REDIS_URL)
        rc.delete(_REDIS_KEY)
    except Exception:
        pass


def search_bm25(
    index_data: dict,
    query: str,
    top_k: int,
    job_ids: list[str] | None = None,
) -> list[dict]:
    """Keyword search via BM25Okapi. Returns results in same schema as vector search."""
    bm25 = index_data["bm25"]
    docs = index_data["docs"]
    metas = index_data["metas"]
    ids = index_data["ids"]

    if not docs:
        return []

    tokens = _tokenize(query)
    raw_scores = bm25.get_scores(tokens)
    max_score = max(raw_scores) if max(raw_scores) > 0 else 1.0

    results = []
    for score, doc, meta, chunk_id in zip(raw_scores, docs, metas, ids):
        if score <= 0:
            continue
        if job_ids and meta.get("job_id") not in job_ids:
            continue
        results.append({
            "id": chunk_id,
            "score": float(score) / max_score,
            "text": meta.get("parent_text", doc),
            "filename": meta.get("filename", ""),
            "page_or_segment": meta.get("page_or_segment", "content"),
            "job_id": meta.get("job_id", ""),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]

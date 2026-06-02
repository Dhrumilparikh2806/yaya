"""
ChromaDB HTTP client helpers.

All chunks from all file types share a single collection (CHROMA_COLLECTION,
default: geminirag_chunks) configured with hnsw:space=cosine.

add_chunks()   — upserts child chunks with their embeddings and metadata dict.
                 The metadata includes job_id, filename, file_type, chunk_index,
                 page_or_segment label, parent_id, parent_text (for hierarchical
                 retrieval), and — for audio/video — speaker_label and
                 speaker_embedding_json.
search()       — cosine similarity search; returns parent_text (if present) as
                 the chunk text so the LLM receives richer context.
rrf_merge()    — Reciprocal Rank Fusion: each result list contributes
                 1/(k + rank) to a shared score; top-k by combined score are
                 returned.  RRF scores are much smaller than cosine similarities
                 and must NOT be compared against CONFIDENCE_THRESHOLD directly.
delete_job_chunks() — removes all chunks for a job before re-indexing.
"""

import chromadb

from app.observability.logging import get_logger

log = get_logger()


def get_chroma_client(settings) -> chromadb.HttpClient:
    return chromadb.HttpClient(host=settings.CHROMA_HOST, port=int(settings.CHROMA_PORT))


def get_or_create_collection(client, settings):
    return client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(collection, chunks: list[dict], embeddings: list[list[float]]) -> None:
    if not chunks:
        return
    import time as _time
    job_id = chunks[0]["job_id"] if chunks else "unknown"
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            collection.upsert(
                ids=[f"{c['job_id']}_{c['chunk_index']}" for c in chunks],
                embeddings=embeddings,
                documents=[c["text"] for c in chunks],
                metadatas=[
                    {
                        "job_id": c["job_id"],
                        "filename": c["filename"],
                        "file_type": c["file_type"],
                        "chunk_index": c["chunk_index"],
                        **c.get("metadata", {}),
                    }
                    for c in chunks
                ],
            )
            log.info("chroma_add_chunks", job_id=job_id, chunk_count=len(chunks))
            return
        except Exception as exc:
            last_exc = exc
            log.warning("chroma_add_chunks_retry", job_id=job_id, attempt=attempt + 1, error=str(exc))
            _time.sleep(5)
    raise RuntimeError(f"ChromaDB add_chunks failed after 3 attempts: {last_exc}")


def search(
    collection,
    query_embedding: list[float],
    top_k: int = 5,
    job_ids: list[str] | None = None,
) -> list[dict]:
    where = {"job_id": {"$in": job_ids}} if job_ids else None
    kwargs = dict(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)
    chunks = []
    for chunk_id, doc, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        # Return parent text if available (hierarchical chunking) — richer context for LLM
        text = meta.get("parent_text") or doc
        chunks.append({
            "id": chunk_id,
            "text": text,
            "score": 1 - dist,
            "filename": meta["filename"],
            "page_or_segment": meta.get("page_or_segment", f"chunk {meta['chunk_index']}"),
            "job_id": meta["job_id"],
        })
    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks


def rrf_merge(
    vector_results: list[dict],
    bm25_results: list[dict],
    top_k: int,
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion — merges vector and BM25 result lists.

    Each result list contributes 1 / (k + rank) to a shared per-chunk score.
    k=60 is the standard value from the original RRF paper; it dampens the
    effect of very high ranks without over-weighting top-1 results.

    IMPORTANT: RRF scores are in the range (0, 1/60] — far smaller than cosine
    similarity scores (0–1).  Do NOT compare rrf_merged scores against
    CONFIDENCE_THRESHOLD; always use the original vector score captured before
    this call.
    """
    scores: dict[str, dict] = {}

    for rank, r in enumerate(vector_results):
        rid = r["id"]
        if rid not in scores:
            scores[rid] = {"rrf": 0.0, "data": r}
        scores[rid]["rrf"] += 1.0 / (k + rank + 1)

    for rank, r in enumerate(bm25_results):
        rid = r["id"]
        if rid not in scores:
            scores[rid] = {"rrf": 0.0, "data": r}
        scores[rid]["rrf"] += 1.0 / (k + rank + 1)

    sorted_items = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)
    results = [s["data"] for s in sorted_items[:top_k]]

    # Overwrite per-chunk score with the merged RRF score for downstream sorting.
    # Callers that need the original cosine score must capture it before this call.
    for item, s in zip(results, sorted_items[:top_k]):
        item["score"] = s["rrf"]

    return results


def delete_job_chunks(collection, job_id: str) -> None:
    try:
        existing = collection.get(where={"job_id": {"$eq": job_id}})
        count = len(existing["ids"])
        if count:
            collection.delete(where={"job_id": {"$eq": job_id}})
            log.info("chroma_delete_chunks", job_id=job_id, chunks_deleted=count)
    except Exception:
        pass

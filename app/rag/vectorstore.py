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
    job_id = chunks[0]["job_id"] if chunks else "unknown"
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
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text": doc,
            "score": 1 - dist,
            "filename": meta["filename"],
            "page_or_segment": meta.get(
                "page_or_segment", f"chunk {meta['chunk_index']}"
            ),
            "job_id": meta["job_id"],
        })
    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks


def delete_job_chunks(collection, job_id: str) -> None:
    try:
        existing = collection.get(where={"job_id": {"$eq": job_id}})
        count = len(existing["ids"])
        if count:
            collection.delete(where={"job_id": {"$eq": job_id}})
            log.info("chroma_delete_chunks", job_id=job_id, chunks_deleted=count)
    except Exception:
        pass

"""
Text embedding via fastembed (BAAI/bge-small-en-v1.5, runs fully locally).

The model is lazy-loaded into a module-level singleton on first call so the
ONNX Runtime graph is compiled once and reused for all subsequent requests.
No external API calls are made — embeddings are free and work offline.

embed_chunks() — batch-embeds a list of chunk dicts; logs token count and
                 latency to UsageLog so embedding cost is tracked alongside
                 Groq/Gemini calls.
embed_query()  — single-vector embed for RAG query and RAGAS re-retrieval.
"""

import time

from app.observability.logging import get_logger, log_llm_call

log = get_logger()

_model_instance = None


def _get_model(model_name: str):
    global _model_instance
    if _model_instance is None:
        from fastembed import TextEmbedding
        log.info("embedding_model_load", model=model_name)
        _model_instance = TextEmbedding(model_name)
    return _model_instance


def embed_chunks(
    chunks: list[dict],
    user_id,
    job_id,
    settings,
    db,
) -> list[list[float]]:
    model = _get_model(settings.EMBEDDING_MODEL)
    texts = [c["text"] for c in chunks]
    start = time.time()

    vectors = [v.tolist() for v in model.embed(texts)]

    latency_ms = int((time.time() - start) * 1000)
    log.info(
        "embed_batch_done",
        batch_size=len(texts),
        latency_ms=latency_ms,
        model=settings.EMBEDDING_MODEL,
    )
    log_llm_call(
        user_id=user_id,
        job_id=job_id,
        endpoint="embed_chunks",
        model=settings.EMBEDDING_MODEL,
        prompt_tokens=len(" ".join(texts).split()),
        completion_tokens=0,
        latency_ms=latency_ms,
        db=db,
    )
    return vectors


def embed_query(question: str, settings) -> list[float]:
    model = _get_model(settings.EMBEDDING_MODEL)
    return next(model.query_embed(question)).tolist()

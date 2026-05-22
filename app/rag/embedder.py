import time

from google import genai
from google.genai import errors as genai_errors, types as genai_types

from app.observability.logging import get_logger, log_llm_call

log = get_logger()

_BATCH_SIZE = 100
_RETRY_DELAYS = [60, 120, 240]


def embed_chunks(
    chunks: list[dict],
    user_id,
    job_id,
    settings,
    db,
) -> list[list[float]]:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    texts = [c["text"] for c in chunks]
    all_embeddings: list[list[float]] = []

    for batch_num, i in enumerate(range(0, len(texts), _BATCH_SIZE)):
        batch = texts[i : i + _BATCH_SIZE]
        start = time.time()

        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                log.warning("embed_retry", batch=batch_num, attempt=attempt, wait_s=delay)
                time.sleep(delay)
            try:
                response = client.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=batch,
                    config=genai_types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=768,
                    ),
                )
                break
            except genai_errors.ClientError as e:
                if e.code == 429 and attempt < len(_RETRY_DELAYS):
                    continue
                raise
        else:
            raise RuntimeError(f"embed_chunks: exhausted retries on batch {batch_num}")

        latency_ms = int((time.time() - start) * 1000)
        vectors = [emb.values for emb in response.embeddings]
        all_embeddings.extend(vectors)

        log.info(
            "embed_batch_done",
            batch=batch_num,
            batch_size=len(batch),
            latency_ms=latency_ms,
        )
        log_llm_call(
            user_id=user_id,
            job_id=job_id,
            endpoint="embed_chunks",
            model=settings.GEMINI_EMBEDDING_MODEL,
            prompt_tokens=len(" ".join(batch).split()),
            completion_tokens=0,
            latency_ms=latency_ms,
            db=db,
        )

    return all_embeddings


def embed_query(question: str, settings) -> list[float]:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=question,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )
    return response.embeddings[0].values

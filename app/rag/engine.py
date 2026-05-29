import json
import time
from datetime import datetime

import groq as groq_sdk
from fastapi import HTTPException

from app.observability.logging import get_logger, log_llm_call
from app.rag.embedder import embed_query
from app.rag.vectorstore import get_chroma_client, get_or_create_collection, search, rrf_merge
from app.rag.bm25_index import load_bm25, build_bm25, search_bm25

log = get_logger()

RAG_SYSTEM_PROMPT = """You are a document Q&A assistant. Answer ONLY from the numbered context excerpts provided. Do NOT use any knowledge from outside these excerpts.

RULES (each violation counts against faithfulness):
1. Every sentence in your answer MUST be directly supported by a specific excerpt. If a fact is not explicitly written in an excerpt, do not state it.
2. After every factual claim, immediately place the citation marker [n] matching the excerpt number.
3. If the answer is not in the excerpts, respond only with: "The provided documents do not contain this information."
4. Never infer, extrapolate, or combine information creatively. Stick to verbatim or near-verbatim facts from the excerpts.
5. Be concise. No preamble, no filler phrases.
"""


def _resolve_chunks_and_context(question: str, job_ids: list[str] | None, settings) -> dict:
    """Embed question, search ChromaDB, run confidence gate, build prompt. Returns dict."""
    q_embedding = embed_query(question, settings)
    client = get_chroma_client(settings)
    collection = get_or_create_collection(client, settings)

    # Hybrid search: vector + BM25 merged via Reciprocal Rank Fusion
    vector_chunks = search(collection, q_embedding, top_k=settings.RAG_TOP_K * 2, job_ids=job_ids)
    index_data = load_bm25(settings) or build_bm25(collection, settings)
    bm25_chunks = search_bm25(index_data, question, top_k=settings.RAG_TOP_K * 2, job_ids=job_ids)
    chunks = rrf_merge(vector_chunks, bm25_chunks, top_k=settings.RAG_TOP_K)

    if not chunks:
        if job_ids:
            msg = "The selected document(s) have no searchable text content. Try selecting different documents or search across all documents."
        else:
            msg = "No documents found to search. Please upload and process files first."
        return {"early_return": True, "payload": {
            "answer": msg,
            "citations": [], "confidence_gate_passed": False,
            "avg_similarity_score": 0.0, "prompt_tokens": 0,
            "completion_tokens": 0, "latency_ms": 0, "ragas_scores": None,
        }}

    # Confidence gate uses top vector cosine similarity (0–1 scale), not raw RRF score.
    # RRF scores are ~0.016–0.033 regardless of relevance; vector similarity is calibrated.
    top_vector_score = vector_chunks[0]["score"] if vector_chunks else 0.0
    avg_vector_score = sum(c["score"] for c in vector_chunks) / len(vector_chunks) if vector_chunks else 0.0
    if top_vector_score < settings.CONFIDENCE_THRESHOLD:
        return {"early_return": True, "payload": {
            "answer": "I couldn't find sufficiently relevant information in your documents to answer this question confidently.",
            "citations": [], "confidence_gate_passed": False,
            "avg_similarity_score": top_vector_score, "prompt_tokens": 0,
            "completion_tokens": 0, "latency_ms": 0, "ragas_scores": None,
        }}

    # Parent chunks ≈ 600 words (~3600 chars) — cap at 1200 chars for 6-chunk token budget
    _MAX_CHUNK_CHARS = 1200
    context_parts = [
        f"[{i}] Source: {c['filename']} ({c['page_or_segment']})\n{c['text'][:_MAX_CHUNK_CHARS]}"
        for i, c in enumerate(chunks, 1)
    ]
    user_prompt = f"Context:\n{chr(10).join(context_parts)}\n\nQuestion: {question}\n\nAnswer (with [n] citation markers):"
    return {"early_return": False, "chunks": chunks, "avg_score": avg_vector_score, "user_prompt": user_prompt}


def query(
    question: str,
    job_ids: list[str] | None,
    user_id,
    db,
    settings,
) -> dict:
    start_total = time.time()

    resolved = _resolve_chunks_and_context(question, job_ids, settings)
    if resolved["early_return"]:
        payload = resolved["payload"]
        payload["latency_ms"] = int((time.time() - start_total) * 1000)
        log.info("rag_query_early_exit", question=question[:100], reason="no_chunks_or_low_confidence")
        return payload

    chunks = resolved["chunks"]
    avg_score = resolved["avg_score"]
    user_prompt = resolved["user_prompt"]

    # Call Groq
    groq_client = groq_sdk.Groq(api_key=settings.GROQ_API_KEY)
    try:
        response = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=512,
        )
    except groq_sdk.RateLimitError as exc:
        log.warning("rag_rate_limit", model=settings.GROQ_MODEL, error=str(exc)[:200])
        raise HTTPException(status_code=429, detail="AI model rate limit reached. Please wait a few minutes and try again.")
    except groq_sdk.APIStatusError as exc:
        if exc.status_code == 413:
            log.warning("rag_request_too_large", model=settings.GROQ_MODEL, error=str(exc)[:200])
            raise HTTPException(status_code=503, detail="Query context too large for model. Try selecting fewer documents.")
        log.error("rag_api_error", model=settings.GROQ_MODEL, error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="AI model error. Please try again.")
    latency_ms = int((time.time() - start_total) * 1000)

    prompt_tokens = response.usage.prompt_tokens if response.usage else 0
    completion_tokens = response.usage.completion_tokens if response.usage else 0
    answer_text = response.choices[0].message.content

    # 7. Log usage
    log_llm_call(
        user_id=user_id,
        endpoint="rag_query",
        model=settings.GROQ_MODEL,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        query_text=question[:500],
        llm_response_preview=answer_text[:500],
        db=db,
    )

    log.info(
        "rag_query",
        question=question[:100],
        retrieved_chunk_count=len(chunks),
        avg_similarity_score=round(avg_score, 4),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )

    # 8. Build citations list
    citations = [
        {
            "index": i + 1,
            "filename": c["filename"],
            "page_or_segment": c["page_or_segment"],
            "excerpt": c["text"][:200],
        }
        for i, c in enumerate(chunks)
    ]

    # 9. Save to QueryHistory
    from app.models.db import QueryHistory

    qh = QueryHistory(
        user_id=user_id,
        question=question,
        answer=answer_text,
        citations=json.dumps(citations),
        job_ids_queried=json.dumps([str(j) for j in (job_ids or [])]),
        chunk_count_retrieved=len(chunks),
        avg_similarity_score=avg_score,
        confidence_gate_passed=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        created_at=datetime.utcnow(),
    )
    db.add(qh)
    db.commit()
    db.refresh(qh)

    # 10. Enqueue async RAGAS evaluation
    from app.workers.tasks import compute_ragas
    compute_ragas.delay(str(qh.id))

    return {
        "answer": answer_text,
        "citations": citations,
        "confidence_gate_passed": True,
        "avg_similarity_score": avg_score,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "ragas_scores": None,
    }

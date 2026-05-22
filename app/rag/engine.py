import json
import time
from datetime import datetime

from google import genai
from google.genai import types as genai_types

from app.observability.logging import get_logger, log_llm_call
from app.rag.embedder import embed_query
from app.rag.vectorstore import get_chroma_client, get_or_create_collection, search

log = get_logger()

RAG_SYSTEM_PROMPT = """You are a precise document assistant. You MUST follow these rules:
1. Answer ONLY using information from the provided context below.
2. If the answer is not in the context, say exactly: "I don't have enough information in the provided documents to answer this question."
3. Do not use any outside knowledge.
4. Cite your sources using [1], [2], [3] etc. corresponding to the context items below.
5. Be concise and direct.
"""


def _resolve_chunks_and_context(question: str, job_ids: list[str] | None, settings) -> dict:
    """Embed question, search ChromaDB, run confidence gate, build prompt. Returns dict."""
    q_embedding = embed_query(question, settings)
    client = get_chroma_client(settings)
    collection = get_or_create_collection(client, settings)
    chunks = search(collection, q_embedding, top_k=settings.RAG_TOP_K, job_ids=job_ids)

    if not chunks:
        return {"early_return": True, "payload": {
            "answer": "No documents found to search. Please upload and process files first.",
            "citations": [], "confidence_gate_passed": False,
            "avg_similarity_score": 0.0, "prompt_tokens": 0,
            "completion_tokens": 0, "latency_ms": 0, "ragas_scores": None,
        }}

    avg_score = sum(c["score"] for c in chunks) / len(chunks)
    if avg_score < settings.CONFIDENCE_THRESHOLD:
        return {"early_return": True, "payload": {
            "answer": "I couldn't find sufficiently relevant information in your documents to answer this question confidently.",
            "citations": [], "confidence_gate_passed": False,
            "avg_similarity_score": avg_score, "prompt_tokens": 0,
            "completion_tokens": 0, "latency_ms": 0, "ragas_scores": None,
        }}

    context_parts = [
        f"[{i}] Source: {c['filename']} ({c['page_or_segment']})\n{c['text']}"
        for i, c in enumerate(chunks, 1)
    ]
    user_prompt = f"Context:\n{chr(10).join(context_parts)}\n\nQuestion: {question}\n\nAnswer (with [n] citation markers):"
    return {"early_return": False, "chunks": chunks, "avg_score": avg_score, "user_prompt": user_prompt}


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

    # Call Gemini
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = genai_client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=RAG_SYSTEM_PROMPT,
        ),
    )
    latency_ms = int((time.time() - start_total) * 1000)

    prompt_tokens = response.usage_metadata.prompt_token_count or 0
    completion_tokens = response.usage_metadata.candidates_token_count or 0
    answer_text = response.text

    # 7. Log usage
    log_llm_call(
        user_id=user_id,
        endpoint="rag_query",
        model=settings.GEMINI_MODEL,
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

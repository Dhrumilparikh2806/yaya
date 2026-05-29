import json
import re
import uuid as _uuid

import groq as groq_sdk
import redis as redis_sdk

from app.agent.tools import (
    get_job_status,
    list_documents,
    set_agent_user_id,
)
from app.config import settings
from app.observability.logging import get_logger

log = get_logger()

SYNTHESIS_MODEL = "llama-3.1-8b-instant"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days
SESSION_KEY_PREFIX = "agent:session:"

# ---------------------------------------------------------------------------
# Session helpers (Redis-backed)
# ---------------------------------------------------------------------------

def _redis() -> redis_sdk.Redis:
    return redis_sdk.from_url(settings.REDIS_URL, decode_responses=True)


def _load_session(session_id: str) -> list[dict]:
    try:
        data = _redis().get(f"{SESSION_KEY_PREFIX}{session_id}")
        if data:
            return json.loads(data)
    except Exception as exc:
        log.warning("session_load_error", session_id=session_id, error=str(exc))
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _save_session(session_id: str, messages: list[dict]) -> None:
    try:
        _redis().setex(f"{SESSION_KEY_PREFIX}{session_id}", SESSION_TTL, json.dumps(messages))
    except Exception as exc:
        log.warning("session_save_error", session_id=session_id, error=str(exc))


# ---------------------------------------------------------------------------
# Direct ChromaDB retrieval — no extra LLM call
# ---------------------------------------------------------------------------

_AGENT_TOP_K = 5
_CHUNK_EXCERPT = 600  # chars per chunk (400-word chunks are smaller, show more)


def _retrieve_chunks(question: str) -> list[dict]:
    """Hybrid search: vector + BM25 via RRF. Returns top-k chunks with scores."""
    from app.rag.embedder import embed_query
    from app.rag.vectorstore import get_chroma_client, get_or_create_collection, search, rrf_merge
    from app.rag.bm25_index import load_bm25, build_bm25, search_bm25

    q_emb = embed_query(question, settings)
    client = get_chroma_client(settings)
    col = get_or_create_collection(client, settings)

    vector_chunks = search(col, q_emb, top_k=_AGENT_TOP_K * 2)
    index_data = load_bm25(settings) or build_bm25(col, settings)
    bm25_chunks = search_bm25(index_data, question, top_k=_AGENT_TOP_K * 2)
    return rrf_merge(vector_chunks, bm25_chunks, top_k=_AGENT_TOP_K)


def _build_context_block(chunks: list[dict]) -> str:
    """Format retrieved chunks as a compact numbered context block."""
    parts = []
    for i, c in enumerate(chunks, 1):
        excerpt = c["text"][:_CHUNK_EXCERPT]
        parts.append(f"[{i}] {c['filename']} ({c['page_or_segment']}): {excerpt}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Intent classification — deterministic, no LLM needed
# ---------------------------------------------------------------------------

_GREETING_RE = re.compile(
    r"^(hi+|hello|hey|thanks?|thank\s+you|ok(ay)?|bye|good\s*(bye)?|great|"
    r"perfect|got\s+it|sounds\s+good|alright|sure|cool|nice|yep|nope?|yes|no|"
    r"awesome|makes\s+sense|understood)[!.,?'\s]*$",
    re.IGNORECASE,
)

_LIST_DOCS_RE = re.compile(
    r"\b(?:list|show|what|which|how\s+many)\b.{0,25}\b(?:documents?|files?|uploaded|available|processed)\b",
    re.IGNORECASE,
)

_JOB_STATUS_RE = re.compile(
    r"\bjob[_\s-]?id\b|"
    r"\b(status|progress|check).{0,20}\bjob\b|"
    r"\bjob.{0,20}(status|progress|check)\b",
    re.IGNORECASE,
)

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _classify(message: str) -> str:
    """Returns: 'chitchat' | 'list_docs' | 'job_status' | 'rag_query'"""
    stripped = message.strip()
    if _GREETING_RE.match(stripped):
        return "chitchat"
    if _LIST_DOCS_RE.search(stripped):
        return "list_docs"
    if _JOB_STATUS_RE.search(stripped) and _UUID_RE.search(stripped):
        return "job_status"
    return "rag_query"


def _extract_uuid(text: str) -> str | None:
    m = _UUID_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an intelligent document assistant for MasterCRM.

When document context is provided between <context> tags:
- Answer ONLY using facts explicitly stated in that context.
- Cite every claim with [n] matching the numbered source.
- If the answer is not in the context, say: "I don't have that information in the provided documents."
- Never guess, infer, or use outside knowledge.

Use conversation history to resolve follow-up questions (e.g. "what about them?" refers to the last entity discussed).
For greetings and chitchat, respond naturally without referencing documents."""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_agent(message: str, user_id: str, session_id: str | None = None) -> dict:
    if session_id is None:
        session_id = str(_uuid.uuid4())

    set_agent_user_id(user_id)

    full_history = _load_session(session_id)
    # Keep system prompt + last 10 messages to limit context growth
    system_msg = full_history[0]
    recent = full_history[-10:] if len(full_history) > 11 else full_history[1:]
    messages = [system_msg] + recent
    messages.append({"role": "user", "content": message})

    client = groq_sdk.Groq(api_key=settings.GROQ_API_KEY)
    tool_names_called: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    intent = _classify(message)
    log.info("agent_intent", intent=intent, message_preview=message[:80])

    # -----------------------------------------------------------------------
    # Step 1 — Gather context based on intent
    # -----------------------------------------------------------------------
    context_injection = ""  # extra text appended to the user turn

    if intent == "list_docs":
        result = list_documents()
        tool_names_called.append("list_documents")
        context_injection = f"\n\n<document_list>\n{json.dumps(result, indent=2)}\n</document_list>"

    elif intent == "job_status":
        job_id = _extract_uuid(message)
        if job_id:
            result = get_job_status(job_id)
            tool_names_called.append("get_job_status")
            context_injection = f"\n\n<job_status>\n{json.dumps(result, indent=2)}\n</job_status>"
        else:
            intent = "rag_query"

    if intent == "rag_query":
        try:
            chunks = _retrieve_chunks(message)
            if chunks:
                avg_score = sum(c["score"] for c in chunks) / len(chunks)
                if avg_score >= settings.CONFIDENCE_THRESHOLD:
                    context_block = _build_context_block(chunks)
                    context_injection = f"\n\n<context>\n{context_block}\n</context>"
                    tool_names_called.append("query_rag")
                    log.info(
                        "agent_rag_retrieved",
                        chunks=len(chunks),
                        avg_score=round(avg_score, 4),
                    )
                else:
                    log.info("agent_rag_low_confidence", avg_score=round(avg_score, 4))
        except Exception as exc:
            log.error("agent_rag_error", error=str(exc)[:200])

    # Inject retrieved context into the last user message
    if context_injection:
        messages[-1] = {
            "role": "user",
            "content": message + context_injection,
        }

    # -----------------------------------------------------------------------
    # Step 2 — Single LLM call for synthesis
    # -----------------------------------------------------------------------
    final_text = ""
    try:
        resp = client.chat.completions.create(
            model=SYNTHESIS_MODEL,
            messages=messages,
            max_tokens=512,
        )
        if resp.usage:
            prompt_tokens = resp.usage.prompt_tokens or 0
            completion_tokens = resp.usage.completion_tokens or 0
        final_text = resp.choices[0].message.content or ""
        # Store the clean user message (without injected context) in history
        messages[-1] = {"role": "user", "content": message}
        messages.append(resp.choices[0].message.model_dump(exclude_none=True))
    except groq_sdk.RateLimitError as exc:
        log.warning("agent_rate_limit", error=str(exc)[:200])
        final_text = "I'm hitting a rate limit right now. Please wait a few seconds and try again."
        messages[-1] = {"role": "user", "content": message}
    except Exception as exc:
        log.error("agent_synthesis_error", error=str(exc)[:300])
        final_text = "Something went wrong generating a response. Please try again."
        messages[-1] = {"role": "user", "content": message}

    # Persist full unbounded history to Redis (trimming is only for the LLM window)
    full_history.append({"role": "user", "content": message})
    if final_text and not final_text.startswith("I'm hitting a rate limit") and not final_text.startswith("Something went wrong"):
        full_history.append({"role": "assistant", "content": final_text})
    _save_session(session_id, full_history)

    log.info(
        "agent_run_complete",
        user_id=user_id,
        session_id=session_id,
        intent=intent,
        tool_call_count=len(tool_names_called),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return {
        "response": final_text,
        "tool_calls_made": tool_names_called,
        "session_id": session_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

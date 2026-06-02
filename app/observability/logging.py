"""
Structured logging and LLM call tracking.

configure_logging() — call once at startup to set up structlog with ISO timestamps
                      and JSON output.
get_logger()        — returns a structlog BoundLogger; bind job_id / user_id as needed.
log_llm_call()      — writes a UsageLog row to PostgreSQL AND emits a structlog
                      'llm_call' event, so every Groq/Gemini/Whisper/embed API
                      call is observable both in the DB and in the JSON log stream.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def get_logger():
    return structlog.get_logger()


def log_llm_call(
    *,
    user_id,
    job_id=None,
    endpoint: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    query_text: Optional[str] = None,
    llm_response_preview: Optional[str] = None,
    db,
) -> None:
    from app.models.db import UsageLog

    log_entry = UsageLog(
        user_id=user_id,
        job_id=job_id,
        endpoint=endpoint,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms,
        query_text=query_text,
        llm_response_preview=llm_response_preview,
        created_at=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()

    get_logger().info(
        "llm_call",
        endpoint=endpoint,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        job_id=str(job_id) if job_id else None,
    )

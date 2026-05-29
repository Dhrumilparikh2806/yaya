import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from app.deps import get_current_user, get_db
from app.models.db import Job, JobStatus, User

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    job_ids: Optional[list[uuid.UUID]] = None

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()


@router.post("/query")
def query_documents(
    req: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.config import settings
    from app.rag import engine

    if req.job_ids is not None:
        for jid in req.job_ids:
            job = db.get(Job, jid)
            if not job:
                raise HTTPException(status_code=404, detail=f"Job {jid} not found")
            if job.status != JobStatus.completed:
                raise HTTPException(status_code=400, detail=f"Job {jid} is not COMPLETED")
        job_ids_str = [str(j) for j in req.job_ids]
    else:
        # No filter — search all completed documents (shared knowledge base)
        job_ids_str = None

    return engine.query(
        question=req.question,
        job_ids=job_ids_str,
        user_id=current_user.id,
        db=db,
        settings=settings,
    )


@router.post("/query/stream")
def query_stream(
    req: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Streaming RAG query — returns Server-Sent Events with answer chunks."""
    from app.config import settings as _settings

    if req.job_ids is not None:
        for jid in req.job_ids:
            job = db.get(Job, jid)
            if not job:
                raise HTTPException(status_code=404, detail=f"Job {jid} not found")
            if job.status != JobStatus.completed:
                raise HTTPException(status_code=400, detail=f"Job {jid} is not COMPLETED")
        job_ids_str = [str(j) for j in req.job_ids]
    else:
        # No filter — search all completed documents (shared knowledge base)
        job_ids_str = None

    def event_stream():
        from app.rag.engine import RAG_SYSTEM_PROMPT, _resolve_chunks_and_context
        from google import genai
        from google.genai import types as genai_types

        try:
            result = _resolve_chunks_and_context(req.question, job_ids_str, _settings)
            if result.get("early_return"):
                yield f"data: {json.dumps({'type': 'done', **result['payload']})}\n\n"
                return

            chunks = result["chunks"]
            user_prompt = result["user_prompt"]
            avg_score = result["avg_score"]

            genai_client = genai.Client(api_key=_settings.GEMINI_API_KEY)
            full_text = ""
            for chunk in genai_client.models.generate_content_stream(
                model=_settings.GEMINI_MODEL,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(system_instruction=RAG_SYSTEM_PROMPT),
            ):
                piece = chunk.text or ""
                if piece:
                    full_text += piece
                    yield f"data: {json.dumps({'type': 'chunk', 'text': piece})}\n\n"

            citations = [
                {"index": i + 1, "filename": c["filename"], "page_or_segment": c["page_or_segment"], "excerpt": c["text"][:200]}
                for i, c in enumerate(chunks)
            ]
            yield f"data: {json.dumps({'type': 'done', 'answer': full_text, 'citations': citations, 'confidence_gate_passed': True, 'avg_similarity_score': avg_score, 'ragas_scores': None})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

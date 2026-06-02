"""
Agent conversation endpoints.

POST /v1/agent/chat               — multi-turn document chat powered by Groq.
                                    Accepts an optional session_id; creates a
                                    new UUID session if not provided.  Session
                                    history is stored in Redis (7-day TTL).
DELETE /v1/agent/session/{id}     — clear a specific session's history from Redis.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_current_user
from app.models.db import User

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@router.post("/agent/chat")
async def agent_chat(
    req: AgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    from app.agent.agent import run_agent

    return await run_agent(
        message=req.message,
        user_id=str(current_user.id),
        session_id=req.session_id,
    )


@router.delete("/agent/session/{session_id}")
async def clear_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.agent.agent import SESSION_KEY_PREFIX, _redis
    try:
        _redis().delete(f"{SESSION_KEY_PREFIX}{session_id}")
    except Exception:
        pass
    return {"cleared": session_id}

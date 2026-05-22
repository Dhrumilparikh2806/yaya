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

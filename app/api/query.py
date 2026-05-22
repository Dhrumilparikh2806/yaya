import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from app.deps import get_current_user, get_db
from app.models.db import Job, JobStatus, User, UserRole

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
            if job.user_id != current_user.id and current_user.role != UserRole.admin:
                raise HTTPException(status_code=403, detail=f"Access denied to job {jid}")
            if job.status != JobStatus.completed:
                raise HTTPException(status_code=400, detail=f"Job {jid} is not COMPLETED")
        job_ids_str = [str(j) for j in req.job_ids]
    else:
        jobs = db.exec(
            select(Job).where(
                Job.user_id == current_user.id,
                Job.status == JobStatus.completed,
            )
        ).all()
        if not jobs:
            raise HTTPException(
                status_code=400,
                detail="No processed documents found. Please upload and process files first.",
            )
        job_ids_str = [str(j.id) for j in jobs]

    return engine.query(
        question=req.question,
        job_ids=job_ids_str,
        user_id=current_user.id,
        db=db,
        settings=settings,
    )

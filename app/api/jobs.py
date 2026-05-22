import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.deps import get_db, get_current_user
from app.models.db import Job, User, UserRole

router = APIRouter()


class JobResponse(BaseModel):
    job_id: str
    filename: str
    file_type: str
    status: str
    step: Optional[str]
    retry_count: int
    error_type: Optional[str]
    error_message: Optional[str]
    chunk_count: Optional[int]
    created_at: datetime
    updated_at: datetime


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    job = db.get(Job, job_uuid)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.user_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return JobResponse(
        job_id=str(job.id),
        filename=job.filename,
        file_type=job.file_type,
        status=job.status.value,
        step=job.step,
        retry_count=job.retry_count,
        error_type=job.error_type.value if job.error_type else None,
        error_message=job.error_message,
        chunk_count=job.chunk_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )

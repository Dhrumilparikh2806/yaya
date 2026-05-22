import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.deps import get_db, get_current_user
from app.models.db import Job, JobStatus, User, UserRole

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


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.admin:
        jobs = db.exec(select(Job)).all()
    else:
        jobs = db.exec(select(Job).where(Job.user_id == current_user.id)).all()
    return [
        JobResponse(
            job_id=str(j.id), filename=j.filename, file_type=j.file_type,
            status=j.status.value, step=j.step, retry_count=j.retry_count,
            error_type=j.error_type.value if j.error_type else None,
            error_message=j.error_message, chunk_count=j.chunk_count,
            created_at=j.created_at, updated_at=j.updated_at,
        )
        for j in jobs
    ]


@router.post("/jobs/{job_id}/reprocess", status_code=202)
def reprocess_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-queue a completed or failed job through the full processing pipeline."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found")

    job = db.get(Job, job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Access denied")

    from app.workers.tasks import process_file, update_job_state

    job.retry_count = 0
    job.error_message = None
    job.error_type = None
    db.add(job)
    db.commit()

    update_job_state(db, job_uuid, JobStatus.pending, step="queued")
    process_file.delay(job_id)

    return {"job_id": job_id, "status": "PENDING", "message": "Re-queued for processing"}

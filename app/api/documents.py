"""
Document endpoints.

GET /v1/documents               — list all completed documents that produced at
                                  least one chunk (chunk_count > 0).  Shared
                                  across all authenticated users.
GET /v1/documents/{id}/summary  — return the structured summary JSON stored in
                                  Job.result by the processor (title, key_points,
                                  speakers, sheets, etc. — format varies by
                                  file type).
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.deps import get_current_user, get_db
from app.models.db import Job, JobStatus, User, UserRole

router = APIRouter()


@router.get("/documents")
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Job).where(
        Job.status == JobStatus.completed,
        Job.chunk_count > 0,
    )
    jobs = db.exec(stmt).all()
    return [
        {
            "job_id": str(j.id),
            "filename": j.filename,
            "file_type": j.file_type,
            "status": j.status.value,
            "chunk_count": j.chunk_count,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]


@router.get("/documents/{job_id}/summary")
def get_document_summary(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # All users can view any document summary
    if job.status != JobStatus.completed:
        raise HTTPException(status_code=400, detail="Job is not COMPLETED")

    try:
        summary = json.loads(job.result) if job.result else {}
    except Exception:
        summary = {"raw": job.result}

    return {
        "job_id": str(job.id),
        "filename": job.filename,
        "file_type": job.file_type,
        "summary": summary,
    }

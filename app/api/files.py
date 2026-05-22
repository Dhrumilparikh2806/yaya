import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlmodel import Session

from app.config import settings
from app.deps import get_db, get_current_user
from app.models.db import Job, JobStatus, User
from app.observability.logging import get_logger
from app.workers.tasks import process_file, update_job_state

router = APIRouter()
log = get_logger()

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp4": "video",
    ".mov": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
}

MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    file_type: str
    status: str


@router.post("/files/upload", response_model=UploadResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suffix = Path(file.filename).suffix.lower()
    file_type = EXTENSION_MAP.get(suffix)
    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(EXTENSION_MAP.keys())}",
        )

    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 500 MB limit",
        )

    # Sanitise filename — prevent path traversal
    safe_filename = Path(file.filename).name

    job_id = uuid.uuid4()
    dest_dir = Path(settings.UPLOAD_DIR) / str(job_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = str(dest_dir / safe_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    job = Job(
        id=job_id,
        user_id=current_user.id,
        filename=safe_filename,
        file_type=file_type,
        file_path=file_path,
        file_size_bytes=file_size,
        status=JobStatus.pending,
        step="queued",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    update_job_state(db, job_id, JobStatus.pending, step="queued")

    process_file.delay(str(job_id))

    log.info(
        "file_uploaded",
        user_id=str(current_user.id),
        filename=safe_filename,
        file_type=file_type,
        job_id=str(job_id),
        file_size_bytes=file_size,
    )

    return UploadResponse(
        job_id=str(job_id),
        filename=safe_filename,
        file_type=file_type,
        status="PENDING",
    )

import json
import shutil
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

from sqlmodel import Session, select

from app.models.db import Job, JobStatus, get_engine
from app.observability.logging import get_logger

log = get_logger()

_current_user_id: ContextVar[str | None] = ContextVar("_current_user_id", default=None)


def set_agent_user_id(user_id: str):
    return _current_user_id.set(user_id)


def ingest_file(file_path: str) -> dict:
    """
    Submit a file for background processing.
    Args:
        file_path: Absolute path to the file to process.
    Returns:
        job_id: UUID of the created job.
        status: Initial status (always PENDING).
        message: Confirmation message.
    """
    start = time.monotonic()
    try:
        from app.config import settings
        from app.workers.tasks import process_file

        user_id_str = _current_user_id.get()
        if not user_id_str:
            return {"error": "No authenticated user context"}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        suffix = path.suffix.lower().lstrip(".")
        file_type_map = {
            "pdf": "pdf", "docx": "docx", "xlsx": "xlsx", "csv": "csv",
            "png": "image", "jpg": "image", "jpeg": "image",
            "gif": "image", "webp": "image",
            "mp4": "video", "avi": "video", "mov": "video",
            "mp3": "audio", "wav": "audio", "m4a": "audio",
        }
        file_type = file_type_map.get(suffix)
        if not file_type:
            return {"error": f"Unsupported file extension: .{suffix}"}

        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / path.name
        shutil.copy2(file_path, dest)

        with Session(get_engine()) as db:
            job = Job(
                user_id=uuid.UUID(user_id_str),
                filename=path.name,
                file_type=file_type,
                file_path=str(dest),
                file_size_bytes=path.stat().st_size,
                status=JobStatus.pending,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = str(job.id)

        process_file.delay(job_id)
        result = {"job_id": job_id, "status": "PENDING", "message": f"File '{path.name}' submitted for processing."}
    except Exception as exc:
        result = {"error": str(exc)}

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info("tool_call", tool_name="ingest_file", latency_ms=latency_ms, result_preview=str(result)[:200])
    return result


def get_job_status(job_id: str) -> dict:
    """
    Check the current processing status of a job.
    Args:
        job_id: UUID of the job to check.
    Returns:
        status: PENDING, PROCESSING, COMPLETED, FAILED, or FAILED_PERMANENT.
        step: Current processing step (e.g. 'embedding', 'indexing').
        retry_count: Number of retries so far.
        error_message: Error details if failed, null otherwise.
    """
    start = time.monotonic()
    try:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return {"error": f"Invalid job_id: {job_id}"}

        with Session(get_engine()) as db:
            job = db.get(Job, jid)
            if not job:
                result = {"error": f"Job not found: {job_id}"}
            else:
                result = {
                    "job_id": str(job.id),
                    "status": job.status.value,
                    "step": job.step,
                    "retry_count": job.retry_count,
                    "chunk_count": job.chunk_count,
                    "error_message": job.error_message,
                }
    except Exception as exc:
        result = {"error": str(exc)}

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info("tool_call", tool_name="get_job_status", latency_ms=latency_ms, result_preview=str(result)[:200])
    return result


def query_rag(question: str, job_ids: list[str] | None = None) -> dict:
    """
    Answer a question using the RAG engine across processed documents.
    Args:
        question: Natural language question to answer.
        job_ids: Optional list of job UUIDs to restrict search to. If null, searches all documents.
    Returns:
        answer: Grounded answer with [n] citation markers.
        citations: List of source references.
        confidence_gate_passed: Whether enough relevant context was found.
    """
    start = time.monotonic()
    try:
        from app.config import settings
        from app.rag import engine

        user_id_str = _current_user_id.get()
        if not user_id_str:
            return {"error": "No authenticated user context"}

        with Session(get_engine()) as db:
            result = engine.query(
                question=question,
                job_ids=job_ids,
                user_id=uuid.UUID(user_id_str),
                db=db,
                settings=settings,
            )
    except Exception as exc:
        result = {"error": str(exc)}

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info("tool_call", tool_name="query_rag", latency_ms=latency_ms, result_preview=str(result)[:200])
    return result


def list_documents(limit: int = 20) -> dict:
    """
    List successfully processed documents available for querying.
    Returns a summary with total count plus up to `limit` recent documents.
    """
    start = time.monotonic()
    try:
        with Session(get_engine()) as db:
            stmt = select(Job).where(Job.status == JobStatus.completed)
            jobs = db.exec(stmt).all()
            total = len(jobs)
            shown = jobs[:limit]
            result = {
                "total_documents": total,
                "showing": len(shown),
                "documents": [
                    {
                        "job_id": str(j.id),
                        "filename": j.filename,
                        "file_type": j.file_type,
                        "chunk_count": j.chunk_count,
                    }
                    for j in shown
                ],
            }
    except Exception as exc:
        log.error("tool_call_error", tool_name="list_documents", error=str(exc))
        result = {"total_documents": 0, "showing": 0, "documents": []}

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info("tool_call", tool_name="list_documents", latency_ms=latency_ms, result_preview=str(result)[:200])
    return result


def summarize_document(job_id: str) -> dict:
    """
    Retrieve the structured summary for a processed document.
    Args:
        job_id: UUID of the completed job.
    Returns:
        The structured summary dict generated during processing (varies by file type).
    """
    start = time.monotonic()
    try:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return {"error": f"Invalid job_id: {job_id}"}

        with Session(get_engine()) as db:
            job = db.get(Job, jid)
            if not job:
                result = {"error": f"Job not found: {job_id}"}
            elif job.status != JobStatus.completed:
                result = {"error": f"Job {job_id} is not COMPLETED (status: {job.status.value})"}
            else:
                try:
                    summary = json.loads(job.result) if job.result else {}
                except Exception:
                    summary = {"raw": job.result}
                result = {
                    "job_id": str(job.id),
                    "filename": job.filename,
                    "file_type": job.file_type,
                    "summary": summary,
                }
    except Exception as exc:
        result = {"error": str(exc)}

    latency_ms = int((time.monotonic() - start) * 1000)
    log.info("tool_call", tool_name="summarize_document", latency_ms=latency_ms, result_preview=str(result)[:200])
    return result

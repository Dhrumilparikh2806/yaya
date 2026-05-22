import json
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.models.db import Job, JobStatus, ErrorType, get_engine
from app.observability.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger()


# ── State transition helper ────────────────────────────────────────────────────

def update_job_state(
    db: Session,
    job_id,
    status: JobStatus,
    step: Optional[str] = None,
    error_type: Optional[ErrorType] = None,
    error_message: Optional[str] = None,
    chunk_count: Optional[int] = None,
) -> None:
    job = db.get(Job, job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id)))
    job.status = status
    job.updated_at = datetime.utcnow()
    if step is not None:
        job.step = step
    if error_type is not None:
        job.error_type = error_type
    if error_message is not None:
        job.error_message = error_message
    if chunk_count is not None:
        job.chunk_count = chunk_count
    db.add(job)
    db.commit()
    log.info(
        "job_state_change",
        job_id=str(job_id),
        status=status.value,
        step=step,
        retry_count=job.retry_count,
    )


# ── Error classification ───────────────────────────────────────────────────────

def classify_error(exc: Exception) -> tuple[str, bool]:
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg:
        return "RATE_LIMIT", True
    if "400" in msg or "invalid" in msg:
        return "INVALID_INPUT", False
    return "UNKNOWN", True


# ── Main processing task ───────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_file(self, job_id: str):
    from app.config import settings

    with Session(get_engine()) as db:
        job = db.get(Job, uuid.UUID(job_id))
        if not job:
            log.error("process_file_job_not_found", job_id=job_id)
            return

        try:
            update_job_state(db, job_id, JobStatus.processing, step="extracting")

            file_type = job.file_type
            log.info("process_file_start", job_id=job_id, file_type=file_type)

            # ── Dispatch to correct processor ──────────────────────────────
            if file_type == "pdf":
                from app.processors.pdf import PDFProcessor
                processor = PDFProcessor(job=job, settings=settings)
            elif file_type == "docx":
                from app.processors.docx_proc import DOCXProcessor
                processor = DOCXProcessor(job=job, settings=settings)
            elif file_type in ("xlsx", "csv"):
                from app.processors.xlsx_proc import XLSXProcessor
                processor = XLSXProcessor(job=job, settings=settings)
            elif file_type == "image":
                from app.processors.image import ImageProcessor
                processor = ImageProcessor(job=job, settings=settings)
            elif file_type in ("video", "audio"):
                from app.processors.video import VideoAudioProcessor
                processor = VideoAudioProcessor(job=job, settings=settings)
            else:
                raise ValueError(f"Unsupported file_type: {file_type}")

            # ── Extract + summarise ────────────────────────────────────────
            extracted_text, summary = processor.run(db)

            # ── Chunking ──────────────────────────────────────────────────
            update_job_state(db, job_id, JobStatus.processing, step="chunking")

            from app.rag.chunker import chunk_text, chunk_video_segments

            if file_type in ("video", "audio"):
                result_dict = json.loads(job.result) if job.result else {}
                segments = result_dict.get("segments", [])
                chunks = chunk_video_segments(segments, job_id, job.filename)
            else:
                chunks = chunk_text(
                    extracted_text,
                    job_id=job_id,
                    filename=job.filename,
                    file_type=file_type,
                    chunk_size=settings.CHUNK_SIZE,
                    overlap=settings.CHUNK_OVERLAP,
                )

            if not chunks:
                log.warning("no_chunks_produced", job_id=job_id, file_type=file_type)

            # ── Embedding ─────────────────────────────────────────────────
            update_job_state(db, job_id, JobStatus.processing, step="embedding")

            embeddings = []
            if chunks:
                from app.rag.embedder import embed_chunks
                embeddings = embed_chunks(chunks, job.user_id, job.id, settings, db)

            # ── Indexing ──────────────────────────────────────────────────
            update_job_state(db, job_id, JobStatus.processing, step="indexing")

            if chunks and embeddings:
                from app.rag.vectorstore import get_chroma_client, get_or_create_collection, delete_job_chunks, add_chunks
                client = get_chroma_client(settings)
                collection = get_or_create_collection(client, settings)
                delete_job_chunks(collection, job_id)
                add_chunks(collection, chunks, embeddings)

            # ── Complete ──────────────────────────────────────────────────
            update_job_state(
                db, job_id, JobStatus.completed,
                step="completed",
                chunk_count=len(chunks),
            )
            log.info("process_file_completed", job_id=job_id, chunk_count=len(chunks))

        except Exception as exc:
            error_type_str, retryable = classify_error(exc)
            error_type = ErrorType(error_type_str)

            # Refresh retry count
            db.refresh(job)
            job.retry_count += 1
            db.add(job)
            db.commit()

            log.error(
                "process_file_error",
                job_id=job_id,
                error_type=error_type_str,
                retryable=retryable,
                retry_count=job.retry_count,
                error=str(exc),
            )

            if retryable and self.request.retries < self.max_retries:
                update_job_state(
                    db, job_id, JobStatus.failed,
                    step="failed",
                    error_type=error_type,
                    error_message=str(exc)[:500],
                )
                countdown = settings.CELERY_RETRY_BACKOFF * (2 ** self.request.retries)
                raise self.retry(exc=exc, countdown=countdown)
            else:
                update_job_state(
                    db, job_id, JobStatus.failed_permanent,
                    step="failed",
                    error_type=error_type,
                    error_message=str(exc)[:500],
                )


# ── RAGAS evaluation task ─────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=2)
def compute_ragas(self, query_history_id: str):
    from app.config import settings
    from app.models.db import QueryHistory

    with Session(get_engine()) as db:
        qh = db.get(QueryHistory, uuid.UUID(query_history_id))
        if not qh:
            log.error("compute_ragas_not_found", query_history_id=query_history_id)
            return

        try:
            from app.evaluation.ragas_eval import compute_ragas_scores
            from app.rag.embedder import embed_query
            from app.rag.vectorstore import (
                get_chroma_client, get_or_create_collection, search
            )
            import json as _json

            job_ids = _json.loads(qh.job_ids_queried) if qh.job_ids_queried else None

            # Re-embed the question to retrieve context chunks
            q_embedding = embed_query(qh.question, settings)
            client = get_chroma_client(settings)
            collection = get_or_create_collection(client, settings)
            chunks = search(collection, q_embedding, top_k=settings.RAG_TOP_K, job_ids=job_ids or None)
            contexts = [c["text"] for c in chunks]

            scores = compute_ragas_scores(
                question=qh.question,
                answer=qh.answer,
                contexts=contexts,
                ground_truth=None,
                settings=settings,
            )

            qh.ragas_scores = _json.dumps(scores)
            qh.ragas_computed_at = datetime.utcnow()
            db.add(qh)
            db.commit()

            log.info(
                "ragas_computed",
                query_id=query_history_id,
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
            )

        except Exception as exc:
            log.error("compute_ragas_error", query_history_id=query_history_id, error=str(exc))
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=60)

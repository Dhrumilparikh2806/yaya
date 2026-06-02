"""
GeminiRAG — End-to-End Pipeline Test
=====================================
Tests all supported file formats (PDF, DOCX, CSV, XLSX, Image) through the
full pipeline: processor → chunker → embedder → ChromaDB → RAG query → RAGAS.

Everything is logged with structlog JSON. Every Gemini call logs tokens + latency
to usage_logs. Every job state transition is written to the jobs table.

Redis / Celery is NOT required — tasks run inline (bypassing the broker).

Usage (from the geminirag directory):
    py scripts/run_pipeline_test.py

Output:
    C:/tmp/pipeline_test_report.json   — full per-file and per-query results
    C:/tmp/ragas_test_set.json         — ready to pass to scripts/ragas_baseline.py
    Structlog JSON lines to stdout
"""

import json
import sys
import time
import uuid
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── bootstrap path so app.* imports work ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── app imports ───────────────────────────────────────────────────────────────
from app.config import settings
from app.observability.logging import configure_logging, get_logger
from app.models.db import (
    User, UserRole, Job, JobStatus, ErrorType, UsageLog, QueryHistory, get_engine
)
from app.security import hash_password
from app.rag.chunker import chunk_text, chunk_video_segments
from app.rag.embedder import embed_chunks, embed_query
from app.rag.vectorstore import (
    get_chroma_client, get_or_create_collection, add_chunks, search, delete_job_chunks
)
from app.rag.engine import query as rag_query, _resolve_chunks_and_context
from app.evaluation.ragas_eval import compute_ragas_scores
from sqlmodel import Session, select

# ── monkey-patch compute_ragas.delay so it doesn't call Redis ─────────────────
try:
    from app.workers import tasks as _celery_tasks
    _celery_tasks.compute_ragas.delay = lambda *a, **kw: None
except Exception:
    pass

# ── configure logging ─────────────────────────────────────────────────────────
configure_logging()
log = get_logger().bind(script="run_pipeline_test")

# ── constants ─────────────────────────────────────────────────────────────────
DATASET_DIR = ROOT / "Data set"
UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = Path("C:/tmp/pipeline_test_report.json")
RAGAS_TEST_SET_PATH = Path("C:/tmp/ragas_test_set.json")
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

TEST_USER_EMAIL = "pipeline_test@geminirag.internal"
TEST_USER_PASSWORD = "PipelineTest1!"

# ── file selection — one representative per format (organised structure) ──────
TEST_FILES = [
    {
        "path": DATASET_DIR / "PDF" / "1706.03762v7 (1).pdf",
        "file_type": "pdf",
        "label": "PDF — Attention Is All You Need (research paper)",
        "ragas_questions": [
            {
                "question": "What is the Transformer model and what makes it different from previous sequence transduction models?",
                "ground_truth": "The Transformer is a model architecture based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. It allows for significantly more parallelization and achieves better translation quality than previous recurrent and convolutional models.",
            },
            {
                "question": "What BLEU score did the Transformer achieve on WMT 2014 English-to-German translation?",
                "ground_truth": "The Transformer achieved 28.4 BLEU on the WMT 2014 English-to-German translation task, outperforming all previously published models.",
            },
            {
                "question": "How many attention heads does the base Transformer model use, and what is its model dimensionality?",
                "ground_truth": "The base Transformer model uses 8 parallel attention heads and has a model dimensionality (d_model) of 512.",
            },
        ],
    },
    {
        "path": DATASET_DIR / "DOCX" / "2d16a7517bab3caeb3c68a787d25cf24d66f5a12129e76d4d805f2ea7db54802.docx",
        "file_type": "docx",
        "label": "DOCX — business document",
        "ragas_questions": [],  # auto-generated from summary after processing
    },
    {
        "path": DATASET_DIR / "dome_dataset_M1.csv",
        "file_type": "csv",
        "label": "CSV — dome dataset (small structured data)",
        "ragas_questions": [
            {
                "question": "What data is contained in this dataset?",
                "ground_truth": None,  # no ground truth — test relevancy only
            },
        ],
    },
    {
        "path": DATASET_DIR / "owid-energy-data.xlsx",
        "file_type": "xlsx",
        "label": "XLSX — OWID energy data (capped 500 rows per sheet)",
        "ragas_questions": [
            {
                "question": "What kind of energy data does this spreadsheet contain?",
                "ground_truth": None,
            },
        ],
    },
    {
        "path": DATASET_DIR / "BizCardX_Extracting_Business_Card_Data_with_OCR-main" / "1.png",
        "file_type": "image",
        "label": "Image — business card (OCR + vision)",
        "ragas_questions": [
            {
                "question": "What information is visible on this business card?",
                "ground_truth": None,
            },
        ],
    },
]

# ── confidence gate test (should NOT match anything) ─────────────────────────
GATE_TEST_QUESTION = "What is the recipe for chocolate chip cookies?"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_user(db: Session) -> User:
    """Return test user, creating it if needed."""
    user = db.exec(select(User).where(User.email == TEST_USER_EMAIL)).first()
    if user:
        log.info("test_user_exists", email=TEST_USER_EMAIL, user_id=str(user.id))
        return user
    user = User(
        id=uuid.uuid4(),
        email=TEST_USER_EMAIL,
        hashed_password=hash_password(TEST_USER_PASSWORD),
        role=UserRole.user,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("test_user_created", email=TEST_USER_EMAIL, user_id=str(user.id))
    return user


def _create_job(db: Session, user: User, filename: str, file_type: str, file_path: str, file_size: int) -> Job:
    job = Job(
        id=uuid.uuid4(),
        user_id=user.id,
        filename=filename,
        file_type=file_type,
        file_path=file_path,
        file_size_bytes=file_size,
        status=JobStatus.pending,
        step="saving",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    log.info("job_created", job_id=str(job.id), filename=filename, file_type=file_type)
    return job


def _update_job(db: Session, job: Job, status: JobStatus, step: str,
                error_type: Optional[ErrorType] = None, error_message: Optional[str] = None,
                chunk_count: Optional[int] = None) -> None:
    job.status = status
    job.step = step
    job.updated_at = datetime.utcnow()
    if error_type:
        job.error_type = error_type
    if error_message:
        job.error_message = error_message
    if chunk_count is not None:
        job.chunk_count = chunk_count
    db.add(job)
    db.commit()
    log.info(
        "job_state_change",
        job_id=str(job.id),
        status=status,
        step=step,
        chunk_count=chunk_count,
    )


def _copy_file_to_upload_dir(src: Path, job_id: uuid.UUID) -> Path:
    dest_dir = UPLOAD_DIR / str(job_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Per-file pipeline: process → chunk → embed → index
# ─────────────────────────────────────────────────────────────────────────────

def process_file(db: Session, user: User, collection, file_spec: dict) -> Optional[dict]:
    """
    Run the full pipeline for one file. Returns result dict or None on failure.
    Logs every step including tokens + latency.
    """
    src_path = file_spec["path"]
    file_type = file_spec["file_type"]
    label = file_spec["label"]

    if not src_path.exists():
        log.error("file_not_found", path=str(src_path), label=label)
        return {"status": "skipped", "reason": f"File not found: {src_path}", "label": label}

    filename = src_path.name
    file_size = src_path.stat().st_size
    log.info("pipeline_start", label=label, filename=filename, file_size_bytes=file_size)

    # ── create job ────────────────────────────────────────────────────────────
    dest_path = _copy_file_to_upload_dir(src_path, uuid.uuid4())
    job = _create_job(db, user, filename, file_type, str(dest_path), file_size)
    _update_job(db, job, JobStatus.processing, "extracting")

    result = {
        "label": label,
        "filename": filename,
        "file_type": file_type,
        "job_id": str(job.id),
        "file_size_bytes": file_size,
        "status": "pending",
        "steps": {},
    }

    # ── processor ─────────────────────────────────────────────────────────────
    t0 = time.time()
    try:
        processor = _get_processor(job)
        log.info("extracting", job_id=str(job.id), file_type=file_type)
        extracted_text, summary = processor.run(db)
        extract_ms = int((time.time() - t0) * 1000)
        log.info(
            "extracted",
            job_id=str(job.id),
            text_len=len(extracted_text),
            summary_keys=list(summary.keys()) if isinstance(summary, dict) else [],
            latency_ms=extract_ms,
        )
        result["steps"]["extract"] = {
            "status": "ok",
            "text_len": len(extracted_text),
            "summary_keys": list(summary.keys()) if isinstance(summary, dict) else [],
            "latency_ms": extract_ms,
        }
        result["summary"] = summary
    except Exception as exc:
        _update_job(db, job, JobStatus.failed, "failed", ErrorType.unknown, str(exc)[:500])
        log.error("extract_failed", job_id=str(job.id), error=str(exc))
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        return result

    # ── chunking ──────────────────────────────────────────────────────────────
    _update_job(db, job, JobStatus.processing, "chunking")
    t0 = time.time()
    try:
        if file_type == "video_audio":
            segments = summary.get("segments", [])
            chunks = chunk_video_segments(segments, str(job.id), filename)
        else:
            chunks = chunk_text(
                extracted_text, str(job.id), filename, file_type,
                chunk_size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP,
            )
        chunk_ms = int((time.time() - t0) * 1000)
        log.info(
            "chunked",
            job_id=str(job.id),
            chunk_count=len(chunks),
            avg_chunk_words=int(sum(len(c["text"].split()) for c in chunks) / max(len(chunks), 1)),
            latency_ms=chunk_ms,
        )
        result["steps"]["chunk"] = {
            "status": "ok",
            "chunk_count": len(chunks),
            "avg_chunk_words": int(sum(len(c["text"].split()) for c in chunks) / max(len(chunks), 1)),
            "latency_ms": chunk_ms,
            "sample_metadata": chunks[0]["metadata"] if chunks else {},
        }
    except Exception as exc:
        _update_job(db, job, JobStatus.failed, "failed", ErrorType.unknown, str(exc)[:500])
        log.error("chunk_failed", job_id=str(job.id), error=str(exc))
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        return result

    if not chunks:
        log.warning("no_chunks_produced", job_id=str(job.id), file_type=file_type)
        _update_job(db, job, JobStatus.failed, "failed", ErrorType.invalid_input,
                    "Processor produced no text — nothing to chunk.")
        result["status"] = "failed"
        result["error"] = "No chunks produced"
        return result

    # ── embedding ─────────────────────────────────────────────────────────────
    _update_job(db, job, JobStatus.processing, "embedding")
    t0 = time.time()
    try:
        embeddings = embed_chunks(chunks, user.id, job.id, settings, db)
        embed_ms = int((time.time() - t0) * 1000)
        log.info(
            "embedded",
            job_id=str(job.id),
            vector_count=len(embeddings),
            vector_dim=len(embeddings[0]) if embeddings else 0,
            latency_ms=embed_ms,
        )
        result["steps"]["embed"] = {
            "status": "ok",
            "vector_count": len(embeddings),
            "vector_dim": len(embeddings[0]) if embeddings else 0,
            "latency_ms": embed_ms,
        }
    except Exception as exc:
        _update_job(db, job, JobStatus.failed, "failed", ErrorType.unknown, str(exc)[:500])
        log.error("embed_failed", job_id=str(job.id), error=str(exc))
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        return result

    # ── indexing to ChromaDB ──────────────────────────────────────────────────
    _update_job(db, job, JobStatus.processing, "indexing")
    t0 = time.time()
    try:
        delete_job_chunks(collection, str(job.id))   # clean re-run safety
        add_chunks(collection, chunks, embeddings)
        index_ms = int((time.time() - t0) * 1000)

        # verify: query ChromaDB to confirm chunks landed
        stored = collection.get(where={"job_id": {"$eq": str(job.id)}})
        stored_count = len(stored["ids"])
        log.info(
            "indexed",
            job_id=str(job.id),
            chunks_in_chroma=stored_count,
            latency_ms=index_ms,
        )
        result["steps"]["index"] = {
            "status": "ok",
            "chunks_stored": stored_count,
            "latency_ms": index_ms,
        }
    except Exception as exc:
        _update_job(db, job, JobStatus.failed, "failed", ErrorType.unknown, str(exc)[:500])
        log.error("index_failed", job_id=str(job.id), error=str(exc))
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        return result

    # ── complete ──────────────────────────────────────────────────────────────
    _update_job(db, job, JobStatus.completed, "completed", chunk_count=len(chunks))
    result["status"] = "completed"
    log.info(
        "pipeline_complete",
        job_id=str(job.id),
        label=label,
        chunk_count=len(chunks),
        total_ms=sum(s.get("latency_ms", 0) for s in result["steps"].values()),
    )
    return result


def _get_processor(job):
    """Instantiate the correct processor for the given job's file_type."""
    from app.processors.pdf import PDFProcessor
    from app.processors.docx_proc import DOCXProcessor
    from app.processors.xlsx_proc import XLSXProcessor
    from app.processors.image import ImageProcessor
    from app.processors.video import VideoAudioProcessor

    mapping = {
        "pdf":        PDFProcessor,
        "docx":       DOCXProcessor,
        "xlsx":       XLSXProcessor,
        "csv":        XLSXProcessor,   # same processor handles CSV
        "image":      ImageProcessor,
        "video":      VideoAudioProcessor,
        "audio":      VideoAudioProcessor,
        "video_audio": VideoAudioProcessor,
    }
    cls = mapping.get(job.file_type)
    if not cls:
        raise ValueError(f"No processor for file_type={job.file_type!r}")
    return cls(job=job, settings=settings)


# ─────────────────────────────────────────────────────────────────────────────
# RAG retrieval validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_retrieval(db: Session, user_id, collection, job_id: str, question: str,
                       ground_truth: Optional[str], file_label: str) -> dict:
    """
    Embed question → search ChromaDB → call Gemini → compute RAGAS inline.
    Returns full result dict.
    """
    log.info("rag_query_start", job_id=job_id, question=question[:80])
    t0 = time.time()

    try:
        result = rag_query(
            question=question,
            job_ids=[job_id],
            user_id=user_id,
            db=db,
            settings=settings,
        )
    except Exception as exc:
        log.error("rag_query_failed", job_id=job_id, error=str(exc))
        return {"question": question, "status": "error", "error": str(exc)}

    answer = result.get("answer", "")
    citations = result.get("citations", [])
    avg_score = result.get("avg_similarity_score", 0.0)
    conf_passed = result.get("confidence_gate_passed", False)
    latency_ms = result.get("latency_ms", 0)

    log.info(
        "rag_query_done",
        job_id=job_id,
        confidence_gate_passed=conf_passed,
        avg_similarity_score=round(avg_score, 4),
        citation_count=len(citations),
        latency_ms=latency_ms,
    )

    # ── RAGAS inline ──────────────────────────────────────────────────────────
    ragas_scores = None
    if conf_passed and citations:
        contexts = [c["excerpt"] for c in citations]
        try:
            log.info("ragas_compute_start", question=question[:60])
            ragas_scores = compute_ragas_scores(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
                settings=settings,
            )
            log.info(
                "ragas_computed",
                faithfulness=ragas_scores.get("faithfulness"),
                answer_relevancy=ragas_scores.get("answer_relevancy"),
                context_precision=ragas_scores.get("context_precision"),
            )
        except Exception as exc:
            log.error("ragas_compute_failed", error=str(exc))
            ragas_scores = {"error": str(exc)}

    return {
        "file_label": file_label,
        "job_id": job_id,
        "question": question,
        "ground_truth": ground_truth,
        "answer": answer[:500],
        "citation_count": len(citations),
        "avg_similarity_score": avg_score,
        "confidence_gate_passed": conf_passed,
        "latency_ms": int((time.time() - t0) * 1000),
        "ragas_scores": ragas_scores,
        "status": "ok",
    }


def validate_confidence_gate(db: Session, user_id, job_ids: list[str]) -> dict:
    """Test that an out-of-domain question hits the confidence gate."""
    log.info("confidence_gate_test_start", question=GATE_TEST_QUESTION[:60])
    try:
        result = rag_query(
            question=GATE_TEST_QUESTION,
            job_ids=job_ids,
            user_id=user_id,
            db=db,
            settings=settings,
        )
        passed = result.get("confidence_gate_passed", True)
        log.info(
            "confidence_gate_test_done",
            gate_fired=not passed,
            avg_score=result.get("avg_similarity_score"),
        )
        return {
            "question": GATE_TEST_QUESTION,
            "gate_fired": not passed,
            "avg_similarity_score": result.get("avg_similarity_score"),
            "answer_preview": result.get("answer", "")[:200],
        }
    except Exception as exc:
        log.error("confidence_gate_test_failed", error=str(exc))
        return {"question": GATE_TEST_QUESTION, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Auto-generate RAGAS questions from DOCX summary
# ─────────────────────────────────────────────────────────────────────────────

def auto_generate_questions(summary: dict, file_type: str) -> list[dict]:
    """Use Gemini to generate 2 test Q&A pairs from a document summary."""
    from google import genai
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    prompt = f"""Given this document summary, generate 2 factual question-answer pairs
that can be answered directly from the document.

Document type: {file_type}
Summary: {json.dumps(summary, ensure_ascii=False)[:3000]}

Return ONLY valid JSON array with this exact structure, no markdown:
[
  {{"question": "...", "ground_truth": "..."}},
  {{"question": "...", "ground_truth": "..."}}
]

Rules:
- Questions must be answerable from the document
- ground_truth must be a specific factual answer (1-2 sentences)
- Do not generate questions about file names or metadata
"""
    try:
        from google.genai import types as genai_types
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        pairs = json.loads(response.text)
        if isinstance(pairs, list):
            return pairs[:2]
    except Exception as exc:
        log.warning("auto_generate_questions_failed", error=str(exc))
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info("pipeline_test_start", dataset_dir=str(DATASET_DIR))

    engine = get_engine()
    chroma_client = get_chroma_client(settings)
    collection = get_or_create_collection(chroma_client, settings)

    report = {
        "run_at": datetime.utcnow().isoformat(),
        "settings": {
            "gemini_model": settings.GEMINI_MODEL,
            "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
            "chunk_size": settings.CHUNK_SIZE,
            "chunk_overlap": settings.CHUNK_OVERLAP,
            "rag_top_k": settings.RAG_TOP_K,
            "confidence_threshold": settings.CONFIDENCE_THRESHOLD,
        },
        "files": [],
        "rag_queries": [],
        "confidence_gate_test": None,
        "ragas_summary": {},
    }

    ragas_test_set = []

    with Session(engine) as db:
        user = _get_or_create_user(db)

        # ── PHASE 1: process all files ─────────────────────────────────────
        log.info("phase_1_start", message="Processing all dataset files")
        completed_files = []

        for file_spec in TEST_FILES:
            log.info("processing_file", label=file_spec["label"])
            try:
                result = process_file(db, user, collection, file_spec)
            except Exception as exc:
                log.error("process_file_unhandled", label=file_spec["label"], error=str(exc))
                result = {"label": file_spec["label"], "status": "failed", "error": traceback.format_exc()}

            report["files"].append(result)

            if result and result.get("status") == "completed":
                completed_files.append({
                    "file_spec": file_spec,
                    "result": result,
                })

                # Auto-generate questions for DOCX (unknown content)
                if file_spec["file_type"] == "docx" and not file_spec["ragas_questions"]:
                    auto_q = auto_generate_questions(
                        result.get("summary", {}), file_spec["file_type"]
                    )
                    file_spec["ragas_questions"].extend(auto_q)
                    log.info(
                        "auto_generated_questions",
                        file_type=file_spec["file_type"],
                        count=len(auto_q),
                    )

        log.info(
            "phase_1_complete",
            total_files=len(TEST_FILES),
            completed=len(completed_files),
            failed=len(TEST_FILES) - len(completed_files),
        )

        # ── PHASE 2: RAG retrieval validation ─────────────────────────────
        log.info("phase_2_start", message="Validating RAG retrieval per document")
        all_job_ids = [f["result"]["job_id"] for f in completed_files]

        for fc in completed_files:
            job_id = fc["result"]["job_id"]
            file_spec = fc["file_spec"]
            file_label = file_spec["label"]

            for q in file_spec["ragas_questions"]:
                question = q["question"]
                ground_truth = q.get("ground_truth")

                qr = validate_retrieval(
                    db, user.id, collection, job_id,
                    question, ground_truth, file_label
                )
                report["rag_queries"].append(qr)

                # Add to RAGAS test set
                entry = {
                    "question": question,
                    "ground_truth": ground_truth or "",
                    "job_id": job_id,
                    "file_label": file_label,
                }
                ragas_test_set.append(entry)

        # ── PHASE 3: confidence gate test ─────────────────────────────────
        log.info("phase_3_start", message="Testing confidence gate with out-of-domain question")
        gate_result = validate_confidence_gate(db, user.id, all_job_ids)
        report["confidence_gate_test"] = gate_result

        # ── RAGAS summary ─────────────────────────────────────────────────
        all_scores = [
            q["ragas_scores"] for q in report["rag_queries"]
            if q.get("ragas_scores") and "error" not in q["ragas_scores"]
        ]

        metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
        summary_scores = {}
        for metric in metrics:
            vals = [s.get(metric) for s in all_scores if isinstance(s.get(metric), float)]
            if vals:
                summary_scores[metric] = {
                    "avg": round(sum(vals) / len(vals), 4),
                    "min": round(min(vals), 4),
                    "max": round(max(vals), 4),
                    "count": len(vals),
                    "target": {"faithfulness": 0.80, "context_precision": 0.60}.get(metric, 0.70),
                    "pass": sum(vals) / len(vals) >= {"faithfulness": 0.80, "context_precision": 0.60}.get(metric, 0.70),
                }
        report["ragas_summary"] = summary_scores

    # ── save outputs ─────────────────────────────────────────────────────────
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    with open(RAGAS_TEST_SET_PATH, "w", encoding="utf-8") as f:
        json.dump(ragas_test_set, f, indent=2)

    # ── print human-readable summary ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PIPELINE TEST SUMMARY")
    print("=" * 70)
    print(f"\n{'FILE':50} {'STATUS':12} {'CHUNKS':>7}")
    print("-" * 70)
    for f in report["files"]:
        chunks = (f.get("steps", {}).get("index", {}).get("chunks_stored")
                  or f.get("steps", {}).get("chunk", {}).get("chunk_count", "—"))
        print(f"  {f.get('label','?')[:48]:50} {f.get('status','?'):12} {str(chunks):>7}")

    print(f"\n{'RETRIEVAL QUALITY':60} {'ConfGate':>8} {'AvgSim':>7}")
    print("-" * 78)
    for q in report["rag_queries"]:
        label = q.get("file_label", "?")[:35]
        question_short = q.get("question", "")[:22]
        gate = "PASS" if q.get("confidence_gate_passed") else "BLOCKED"
        sim = q.get("avg_similarity_score", 0)
        print(f"  [{label}] {question_short}... {gate:>8} {sim:>7.4f}")

    print(f"\n{'CONFIDENCE GATE TEST'}")
    gate_r = report["confidence_gate_test"]
    print(f"  Q: {gate_r.get('question','?')[:60]}")
    print(f"  Gate fired: {gate_r.get('gate_fired','?')}  Avg sim: {gate_r.get('avg_similarity_score','?')}")

    if report["ragas_summary"]:
        print("\nRAGAS SCORES")
        print("-" * 50)
        for metric, v in report["ragas_summary"].items():
            status = "✓ PASS" if v.get("pass") else "✗ BELOW TARGET"
            print(f"  {metric:<30} avg={v['avg']:.4f}  target≥{v['target']}  {status}")

    print(f"\nReport saved → {REPORT_PATH}")
    print(f"RAGAS test set → {RAGAS_TEST_SET_PATH}  ({len(ragas_test_set)} Q&A pairs)")
    print(f"\nRe-run RAGAS baseline any time:")
    print(f"  py scripts/ragas_baseline.py --test-set {RAGAS_TEST_SET_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()

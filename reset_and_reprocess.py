"""
Reset everything and requeue all jobs for fresh markdown-based processing.

Clears:
  - ChromaDB collection (all vectors)
  - query_history table
  - usage_logs table
  - Resets all jobs to PENDING (chunk_count=0, clears step/error/result)
  - Deletes old extracted.md files
  - Clears log files

Then requeues every job through the Celery pipeline.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv(".env")

from sqlmodel import Session, select, create_engine, text
from app.config import settings
from app.models.db import Job, JobStatus, get_engine

print("=" * 60)
print("RESET AND REPROCESS — MARKDOWN PIPELINE")
print("=" * 60)

# ── 1. Clear ChromaDB ─────────────────────────────────────────
print("\n[1/6] Clearing ChromaDB collection...")
from app.rag.vectorstore import get_chroma_client
client = get_chroma_client(settings)
try:
    client.delete_collection(settings.CHROMA_COLLECTION)
    print(f"      Deleted collection: {settings.CHROMA_COLLECTION}")
except Exception as e:
    print(f"      Collection did not exist or error: {e}")

# Recreate empty collection
from app.rag.vectorstore import get_or_create_collection
col = get_or_create_collection(client, settings)
print(f"      Recreated empty collection: {settings.CHROMA_COLLECTION} (count={col.count()})")

# ── 2. Clear query_history ────────────────────────────────────
print("\n[2/6] Clearing query_history table...")
engine = get_engine()
with Session(engine) as db:
    deleted = db.exec(text("DELETE FROM query_history")).rowcount
    db.commit()
    print(f"      Deleted {deleted} rows from query_history")

# ── 3. Clear usage_logs ───────────────────────────────────────
print("\n[3/6] Clearing usage_logs table...")
with Session(engine) as db:
    deleted = db.exec(text("DELETE FROM usage_logs")).rowcount
    db.commit()
    print(f"      Deleted {deleted} rows from usage_logs")

# ── 4. Reset all jobs to PENDING ─────────────────────────────
print("\n[4/6] Resetting all jobs to PENDING...")
with Session(engine) as db:
    jobs = db.exec(select(Job)).all()
    print(f"      Found {len(jobs)} jobs total")

    # Check which files still exist on disk
    valid_jobs = []
    missing = []
    for job in jobs:
        if Path(job.file_path).exists():
            valid_jobs.append(job)
        else:
            missing.append(job)

    print(f"      {len(valid_jobs)} jobs have files on disk")
    if missing:
        print(f"      {len(missing)} jobs have MISSING files — skipping:")
        for j in missing[:10]:
            print(f"        {j.filename} ({j.id})")

    valid_job_ids = []
    for job in valid_jobs:
        job.status = JobStatus.pending
        job.step = None
        job.chunk_count = 0
        job.error_type = None
        job.error_message = None
        job.result = None
        job.retry_count = 0
        db.add(job)
        valid_job_ids.append(str(job.id))
    db.commit()
    print(f"      Reset {len(valid_job_ids)} jobs to PENDING")

# ── 5. Delete old extracted.md files ─────────────────────────
print("\n[5/6] Removing old extracted.md files...")
upload_dir = Path(settings.UPLOAD_DIR)
removed = 0
for md_file in upload_dir.rglob("extracted.md"):
    try:
        md_file.unlink()
        removed += 1
    except Exception as e:
        print(f"      Could not remove {md_file}: {e}")
print(f"      Removed {removed} extracted.md files")

# ── 6. Clear log files ────────────────────────────────────────
print("\n[6/6] Clearing log files...")
log_files = ["api.log", "api_err.log", "celery.log", "celery_err.log", "chroma.log", "chroma_err.log"]
for lf in log_files:
    lp = Path(__file__).parent / lf
    try:
        if lp.exists():
            lp.write_text("", encoding="utf-8")
            print(f"      Cleared {lf}")
    except Exception as e:
        print(f"      Could not clear {lf}: {e}")

# ── 7. Requeue all valid jobs ─────────────────────────────────
print(f"\n[7/7] Queuing {len(valid_job_ids)} jobs for processing...")
from app.workers.tasks import process_file

queued = 0
for jid in valid_job_ids:
    try:
        process_file.delay(jid)
        queued += 1
    except Exception as e:
        print(f"      Failed to queue {jid}: {e}")

print(f"      Queued {queued} jobs")

print("\n" + "=" * 60)
print(f"DONE — {queued} jobs queued for markdown extraction + re-embedding")
print(f"       ChromaDB is empty — chunks will fill as jobs complete")
print("Monitor progress:  Get-Content celery.log -Wait -Tail 30")
print("=" * 60)

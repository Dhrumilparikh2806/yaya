"""
Day 3 verification script — tests processors directly (bypasses Celery).
Run: python scripts/test_day3.py
"""
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Load .env before any app imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, create_engine

from app.models.db import Job, JobStatus, User, UserRole, UsageLog
from app.observability.logging import configure_logging

configure_logging()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)

import sys as _sys
# Allow passing specific file types: python test_day3.py pdf csv
_filter = set(_sys.argv[1:]) if len(_sys.argv) > 1 else None

_ALL_FILES = {
    "pdf": "C:/tmp/geminirag_test_files/test.pdf",
    "docx": "C:/tmp/geminirag_test_files/test.docx",
    "csv": "C:/tmp/geminirag_test_files/titanic.csv",
}
TEST_FILES = {k: v for k, v in _ALL_FILES.items() if _filter is None or k in _filter}


def get_or_create_test_user(db: Session) -> User:
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "day3test@test.com")).first()
    if not user:
        from app.security import hash_password
        user = User(
            email="day3test@test.com",
            hashed_password=hash_password("test123"),
            role=UserRole.user,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def make_job(db: Session, user_id, file_type: str, file_path: str) -> Job:
    job = Job(
        id=uuid.uuid4(),
        user_id=user_id,
        filename=Path(file_path).name,
        file_type=file_type,
        file_path=file_path,
        file_size_bytes=Path(file_path).stat().st_size,
        status=JobStatus.pending,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_test(file_type: str, file_path: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Testing {file_type.upper()} processor: {file_path}")
    print('='*60)

    with Session(engine) as db:
        user = get_or_create_test_user(db)
        job = make_job(db, user.id, file_type, file_path)
        print(f"Job ID: {job.id}")

        from app.config import settings

        if file_type == "pdf":
            from app.processors.pdf import PDFProcessor
            processor = PDFProcessor(job=job, settings=settings)
        elif file_type == "docx":
            from app.processors.docx_proc import DOCXProcessor
            processor = DOCXProcessor(job=job, settings=settings)
        elif file_type in ("xlsx", "csv"):
            from app.processors.xlsx_proc import XLSXProcessor
            processor = XLSXProcessor(job=job, settings=settings)
        else:
            raise ValueError(f"Unknown type: {file_type}")

        print("Running processor.run(db) ...")
        text, summary = processor.run(db)

        print(f"\nExtracted text length: {len(text)} chars")
        print(f"Summary keys: {list(summary.keys())}")
        print(f"\nSummary preview:")
        print(json.dumps(summary, indent=2)[:800])

        # Verify usage_logs
        from sqlmodel import select
        logs = db.exec(
            select(UsageLog).where(UsageLog.job_id == job.id)
        ).all()
        print(f"\nUsage logs for this job: {len(logs)}")
        for log in logs:
            print(f"  endpoint={log.endpoint} model={log.model} "
                  f"prompt_tokens={log.prompt_tokens} completion_tokens={log.completion_tokens} "
                  f"latency_ms={log.latency_ms}ms")

        # Verify result saved to job
        db.refresh(job)
        assert job.result is not None, "job.result should be set"
        saved = json.loads(job.result)
        print(f"\nJob result saved to DB: {list(saved.keys())}")

        return {
            "file_type": file_type,
            "text_len": len(text),
            "summary_keys": list(summary.keys()),
            "usage_logs": len(logs),
            "tokens": sum(l.prompt_tokens + l.completion_tokens for l in logs),
        }


def main():
    import time
    results = []
    errors = []

    items = [(ft, p) for ft, p in TEST_FILES.items() if Path(p).exists()]
    for i, (file_type, path) in enumerate(items):
        if i > 0:
            print(f"\nWaiting 15s between calls to respect rate limits...")
            time.sleep(15)
        try:
            r = run_test(file_type, path)
            results.append(r)
        except Exception as e:
            import traceback
            print(f"\nERROR testing {file_type}: {e}")
            traceback.print_exc()
            errors.append((file_type, str(e)))

    print(f"\n\n{'='*60}")
    print("DAY 3 VERIFICATION SUMMARY")
    print('='*60)
    for r in results:
        status = "PASS" if r["usage_logs"] > 0 and r["tokens"] > 0 else "WARN"
        print(f"[{status}] {r['file_type'].upper()}: text={r['text_len']}chars "
              f"summary_keys={r['summary_keys']} usage_logs={r['usage_logs']} tokens={r['tokens']}")
    for ft, err in errors:
        print(f"[FAIL] {ft.upper()}: {err}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

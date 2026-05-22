"""
Day 4 verification script — tests ImageProcessor and VideoAudioProcessor directly.
Run: python scripts/test_day4.py
     python scripts/test_day4.py image
     python scripts/test_day4.py audio
"""
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, create_engine

from app.models.db import Job, JobStatus, User, UserRole, UsageLog
from app.observability.logging import configure_logging

configure_logging()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)

_filter = set(sys.argv[1:]) if len(sys.argv) > 1 else None

TEST_FILES = {
    "image": ("C:/tmp/geminirag_test_files/bizcard.png", "image"),
    "audio": ("C:/tmp/geminirag_test_files/test_audio.wav", "audio"),
}
if _filter:
    TEST_FILES = {k: v for k, v in TEST_FILES.items() if k in _filter}


def get_or_create_test_user(db):
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "day4test@test.com")).first()
    if not user:
        from app.security import hash_password
        user = User(
            email="day4test@test.com",
            hashed_password=hash_password("test123"),
            role=UserRole.user,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def make_job(db, user_id, file_type, file_path):
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


def run_test(label, file_path, file_type):
    print(f"\n{'='*60}")
    print(f"Testing {label.upper()} processor: {file_path}")
    print('='*60)

    with Session(engine) as db:
        user = get_or_create_test_user(db)
        job = make_job(db, user.id, file_type, file_path)
        print(f"Job ID: {job.id}")

        from app.config import settings

        if file_type == "image":
            from app.processors.image import ImageProcessor
            processor = ImageProcessor(job=job, settings=settings)
        elif file_type in ("video", "audio"):
            from app.processors.video import VideoAudioProcessor
            processor = VideoAudioProcessor(job=job, settings=settings)
        else:
            raise ValueError(f"Unknown type: {file_type}")

        print("Running processor.run(db) ...")
        text, summary = processor.run(db)

        print(f"\nExtracted text length: {len(text)} chars")
        print(f"Summary keys: {list(summary.keys())}")
        print(f"\nSummary preview:")
        print(json.dumps(summary, indent=2)[:1000])

        from sqlmodel import select
        logs = db.exec(select(UsageLog).where(UsageLog.job_id == job.id)).all()
        print(f"\nUsage logs: {len(logs)}")
        for log in logs:
            print(f"  endpoint={log.endpoint} tokens={log.prompt_tokens}+{log.completion_tokens} "
                  f"latency={log.latency_ms}ms")

        db.refresh(job)
        assert job.result is not None

        return {
            "label": label,
            "summary_keys": list(summary.keys()),
            "usage_logs": len(logs),
            "tokens": sum(l.prompt_tokens + l.completion_tokens for l in logs),
        }


def main():
    import time
    results = []
    errors = []

    items = [(label, path, ftype) for label, (path, ftype) in TEST_FILES.items()
             if Path(path).exists()]

    for i, (label, path, ftype) in enumerate(items):
        if i > 0:
            print(f"\nWaiting 15s between calls...")
            time.sleep(15)
        try:
            r = run_test(label, path, ftype)
            results.append(r)
        except Exception as e:
            import traceback
            print(f"\nERROR testing {label}: {e}")
            traceback.print_exc()
            errors.append((label, str(e)[:200]))

    print(f"\n\n{'='*60}")
    print("DAY 4 VERIFICATION SUMMARY")
    print('='*60)
    for r in results:
        status = "PASS" if r["usage_logs"] > 0 and r["tokens"] > 0 else "WARN"
        print(f"[{status}] {r['label'].upper()}: keys={r['summary_keys']} "
              f"usage_logs={r['usage_logs']} tokens={r['tokens']}")
    for label, err in errors:
        print(f"[FAIL] {label.upper()}: {err}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

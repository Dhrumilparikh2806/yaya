"""
GeminiRAG — Bulk Dataset Processor
====================================
Uploads all PDFs, DOCX, XLSX, and Images from Dataset/scattered/ through the
live API pipeline, polls every job to completion, and prints a full summary.

Usage (from the geminirag directory):
    py scripts/process_dataset.py
"""

import sys
import time
import requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.observability.logging import configure_logging, get_logger

configure_logging()
log = get_logger().bind(script="process_dataset")

# ── config ─────────────────────────────────────────────────────────────────────
API_BASE       = "http://localhost:8000"
DATASET_DIR    = ROOT / "Dataset" / "scattered"
ADMIN_EMAIL    = "admin@test.com"
ADMIN_PASSWORD = "Admin1234!"
POLL_INTERVAL  = 6      # seconds between polls
POLL_TIMEOUT   = 900    # 15 min per file max
UPLOAD_BATCH   = 5      # upload N files then wait before uploading more

SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png", ".webp"}


# ── auth ───────────────────────────────────────────────────────────────────────

def get_token() -> str:
    r = requests.post(f"{API_BASE}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    r.raise_for_status()
    token = r.json()["access_token"]
    log.info("auth_ok", email=ADMIN_EMAIL)
    return token


# ── upload ─────────────────────────────────────────────────────────────────────

def upload_file(token: str, path: Path) -> dict:
    size_mb = path.stat().st_size / (1024 * 1024)
    with open(path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/v1/files/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (path.name, f, "application/octet-stream")},
            timeout=60,
        )
    r.raise_for_status()
    data = r.json()
    log.info("upload_ok", filename=path.name, job_id=data["job_id"],
             size_mb=round(size_mb, 2))
    return data


# ── poll ───────────────────────────────────────────────────────────────────────

def poll_all(token: str, jobs: list[dict]) -> list[dict]:
    """Poll all jobs concurrently until every one reaches a terminal state."""
    headers  = {"Authorization": f"Bearer {token}"}
    pending  = {j["job_id"]: j for j in jobs}
    results  = {}
    last_key = {}
    deadline = time.time() + POLL_TIMEOUT

    print(f"\n  {'FILE':<45}  {'STATUS':<16}  STEP")
    print("  " + "-" * 72)

    while pending and time.time() < deadline:
        for job_id in list(pending.keys()):
            try:
                r = requests.get(f"{API_BASE}/v1/jobs/{job_id}",
                                 headers=headers, timeout=10)
                r.raise_for_status()
                job = r.json()
            except Exception as e:
                print(f"  [poll error] {job_id[:8]}: {e}", flush=True)
                continue

            key = f"{job['status']}:{job.get('step','')}"
            if last_key.get(job_id) != key:
                ts = datetime.now().strftime("%H:%M:%S")
                name = pending[job_id]["filename"][:45]
                print(f"  [{ts}] {name:<45}  {job['status']:<16}  {job.get('step','')}",
                      flush=True)
                last_key[job_id] = key

            if job["status"] in ("COMPLETED", "FAILED", "FAILED_PERMANENT"):
                results[job_id] = {**pending[job_id], **job}
                del pending[job_id]

        if pending:
            time.sleep(POLL_INTERVAL)

    # anything still pending after deadline → timeout
    for job_id, meta in pending.items():
        results[job_id] = {**meta, "status": "TIMEOUT"}

    return list(results.values())


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 72)
    print("  GeminiRAG — Bulk Dataset Processor")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    # Collect files
    if not DATASET_DIR.exists():
        print(f"\n[ERROR] Dataset dir not found: {DATASET_DIR}")
        sys.exit(1)

    all_files = sorted([
        f for f in DATASET_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    ])

    by_type = defaultdict(list)
    for f in all_files:
        ext = f.suffix.lower()
        if ext == ".pdf":
            by_type["PDF"].append(f)
        elif ext == ".docx":
            by_type["DOCX"].append(f)
        elif ext in (".xlsx", ".csv"):
            by_type["XLSX"].append(f)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            by_type["Image"].append(f)

    print(f"\n  Files found:")
    for ftype, files in by_type.items():
        print(f"    {ftype:<8}: {len(files)}")
    print(f"    {'TOTAL':<8}: {len(all_files)}")

    token = get_token()
    all_jobs = []
    t_start  = time.time()

    print(f"\n  Uploading {len(all_files)} files in batches of {UPLOAD_BATCH}...")
    print("  " + "-" * 72)

    for i, path in enumerate(all_files, 1):
        try:
            data = upload_file(token, path)
            all_jobs.append({
                "job_id":    data["job_id"],
                "filename":  path.name,
                "file_type": data["file_type"],
                "t_start":   time.time(),
            })
            print(f"  [{i:>3}/{len(all_files)}] Queued  {path.name[:50]}", flush=True)
        except Exception as e:
            log.error("upload_failed", filename=path.name, error=str(e))
            print(f"  [{i:>3}/{len(all_files)}] UPLOAD FAILED  {path.name}: {e}", flush=True)
            all_jobs.append({
                "job_id":    None,
                "filename":  path.name,
                "file_type": path.suffix[1:],
                "status":    "UPLOAD_FAILED",
                "error":     str(e),
            })

        # Small pause every batch to avoid flooding the API
        if i % UPLOAD_BATCH == 0 and i < len(all_files):
            time.sleep(1)

    # Only poll jobs that were successfully uploaded
    uploadable = [j for j in all_jobs if j.get("job_id")]
    failed_uploads = [j for j in all_jobs if not j.get("job_id")]

    print(f"\n  {len(uploadable)} jobs queued. Polling until all complete...\n")
    results = poll_all(token, uploadable)
    results.extend(failed_uploads)

    elapsed_total = int(time.time() - t_start)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  RESULTS SUMMARY")
    print("=" * 72)
    print(f"\n  {'FILE':<47}  {'TYPE':<6}  {'STATUS':<18}  {'CHUNKS':>6}")
    print("  " + "-" * 84)

    by_status = defaultdict(int)
    total_chunks = 0

    for r in sorted(results, key=lambda x: x.get("file_type", "")):
        status  = r.get("status", "?")
        chunks  = r.get("chunk_count") or "-"
        symbol  = "+" if status == "COMPLETED" else "x"
        ftype   = r.get("file_type", r.get("file_type","?"))[:6]
        print(f"  [{symbol}] {r['filename'][:45]:<45}  {ftype:<6}  {status:<18}  {str(chunks):>6}")
        by_status[status] += 1
        if isinstance(chunks, int):
            total_chunks += chunks

    print("\n  " + "-" * 84)
    print(f"  Total time      : {elapsed_total}s")
    print(f"  Total chunks    : {total_chunks} indexed to ChromaDB")
    print(f"  Completed       : {by_status.get('COMPLETED', 0)}/{len(results)}")
    print(f"  Failed          : {by_status.get('FAILED', 0) + by_status.get('FAILED_PERMANENT', 0) + by_status.get('UPLOAD_FAILED', 0)}")

    # ── Per-type breakdown ───────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  PER-TYPE BREAKDOWN")
    print("=" * 72)
    type_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "completed": 0, "chunks": 0})
    for r in results:
        ft = r.get("file_type", "unknown")
        type_stats[ft]["total"] += 1
        if r.get("status") == "COMPLETED":
            type_stats[ft]["completed"] += 1
            type_stats[ft]["chunks"] += r.get("chunk_count") or 0

    for ft, s in sorted(type_stats.items()):
        print(f"  {ft:<8}: {s['completed']}/{s['total']} completed  |  {s['chunks']} chunks")

    # ── Failed files ─────────────────────────────────────────────────────────────
    failed = [r for r in results if r.get("status") not in ("COMPLETED",)]
    if failed:
        print("\n" + "=" * 72)
        print("  FAILED FILES")
        print("=" * 72)
        for r in failed:
            err = r.get("error_message") or r.get("error") or "unknown"
            print(f"  x {r['filename'][:50]}  [{r.get('status')}]  {str(err)[:100]}")

    # ── Job IDs for RAG queries ──────────────────────────────────────────────────
    completed = [r for r in results if r.get("status") == "COMPLETED"]
    if completed:
        print("\n" + "=" * 72)
        print("  COMPLETED JOB IDs (use for RAG queries)")
        print("=" * 72)
        for r in completed:
            print(f"  {r['filename'][:45]:<45}  {r['job_id']}")

    print("\n" + "=" * 72)
    print(f"  Done — {len(completed)} documents indexed, {total_chunks} chunks in ChromaDB")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()

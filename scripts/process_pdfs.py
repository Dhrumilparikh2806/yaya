"""
GeminiRAG — PDF Pipeline Processor
====================================
Uploads every PDF from Data set/PDF/ through the live API pipeline:
  upload → Celery (extract → summarise → chunk → embed → ChromaDB) → COMPLETED

Logs every step end-to-end with structlog JSON.
Prints a summary table when all PDFs are done.

Usage (from the geminirag directory):
    py scripts/process_pdfs.py
"""

import json
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.observability.logging import configure_logging, get_logger

configure_logging()
log = get_logger().bind(script="process_pdfs")

# ── config ────────────────────────────────────────────────────────────────────
API_BASE        = "http://localhost:8000"
PDF_DIR         = ROOT / "Data set" / "PDF"
ADMIN_EMAIL     = "admin@test.com"
ADMIN_PASSWORD  = "Admin1234!"
POLL_INTERVAL   = 5      # seconds between status polls
POLL_TIMEOUT    = 600    # max seconds to wait per file (10 min)

PDF_FILES = [
    "1706.03762v7 (1).pdf",
    "2303.08774v6.pdf",
    "9789240094703-eng.pdf",
    "WPP2024_Summary-of-Results.pdf",
]


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

def get_token() -> str:
    log.info("auth_login", email=ADMIN_EMAIL)
    r = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    log.info("auth_login_ok", email=ADMIN_EMAIL)
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────────────────────────────────────

def upload_pdf(token: str, pdf_path: Path) -> dict:
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    log.info("upload_start", filename=pdf_path.name, size_mb=round(size_mb, 2))

    with open(pdf_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/v1/files/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (pdf_path.name, f, "application/pdf")},
            timeout=60,
        )

    r.raise_for_status()
    data = r.json()
    log.info(
        "upload_ok",
        filename=pdf_path.name,
        job_id=data["job_id"],
        status=data["status"],
    )
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Poll until done
# ─────────────────────────────────────────────────────────────────────────────

def poll_job(token: str, job_id: str, filename: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + POLL_TIMEOUT
    last_step = None

    while time.time() < deadline:
        r = requests.get(
            f"{API_BASE}/v1/jobs/{job_id}",
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        job = r.json()
        status = job.get("status", "")
        step   = job.get("step", "")

        # Log each new step transition
        if step != last_step:
            log.info(
                "job_step",
                job_id=job_id,
                filename=filename,
                status=status,
                step=step,
                retry_count=job.get("retry_count", 0),
            )
            last_step = step

            # Print live progress to console
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] {filename[:45]:45}  {status:12}  {step}", flush=True)

        if status in ("COMPLETED", "FAILED", "FAILED_PERMANENT"):
            if status == "COMPLETED":
                log.info(
                    "job_completed",
                    job_id=job_id,
                    filename=filename,
                    chunk_count=job.get("chunk_count"),
                )
            else:
                log.error(
                    "job_failed",
                    job_id=job_id,
                    filename=filename,
                    status=status,
                    error_type=job.get("error_type"),
                    error_message=job.get("error_message", "")[:300],
                )
            return job

        time.sleep(POLL_INTERVAL)

    log.error("job_poll_timeout", job_id=job_id, filename=filename, timeout_s=POLL_TIMEOUT)
    return {"job_id": job_id, "status": "TIMEOUT", "filename": filename}


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

def get_document_summary(token: str, job_id: str) -> dict:
    try:
        r = requests.get(
            f"{API_BASE}/v1/documents/{job_id}/summary",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("summary", {})
    except Exception as e:
        log.warning("summary_fetch_failed", job_id=job_id, error=str(e))
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("  GeminiRAG — PDF Pipeline Processor")
    print(f"  Processing {len(PDF_FILES)} PDFs  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Verify PDFs exist
    missing = [f for f in PDF_FILES if not (PDF_DIR / f).exists()]
    if missing:
        print(f"\n[ERROR] Missing files: {missing}")
        sys.exit(1)

    token = get_token()
    results = []

    print(f"\n{'FILE':47}  {'STATUS':12}  STEP")
    print("-" * 70)

    for filename in PDF_FILES:
        pdf_path = PDF_DIR / filename
        t_start = time.time()

        try:
            # 1 — upload
            upload_data = upload_pdf(token, pdf_path)
            job_id = upload_data["job_id"]

            # 2 — poll until done
            final_job = poll_job(token, job_id, filename)
            elapsed = int(time.time() - t_start)

            # 3 — fetch summary if completed
            summary = {}
            if final_job.get("status") == "COMPLETED":
                summary = get_document_summary(token, job_id)

            results.append({
                "filename":    filename,
                "job_id":      job_id,
                "status":      final_job.get("status"),
                "chunk_count": final_job.get("chunk_count"),
                "error":       final_job.get("error_message"),
                "elapsed_s":   elapsed,
                "summary":     summary,
            })

        except Exception as e:
            log.error("pipeline_error", filename=filename, error=str(e))
            results.append({"filename": filename, "status": "ERROR", "error": str(e)})

    # ── Final summary table ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    print(f"\n  {'FILE':47}  {'STATUS':12}  {'CHUNKS':>7}  {'TIME':>6}")
    print("  " + "-" * 66)

    total_chunks = 0
    for r in results:
        chunks = r.get("chunk_count") or "—"
        elapsed = f"{r.get('elapsed_s','?')}s"
        status  = r.get("status", "?")
        color   = "✓" if status == "COMPLETED" else "✗"
        print(f"  {color} {r['filename'][:45]:45}  {status:12}  {str(chunks):>7}  {elapsed:>6}")
        if isinstance(chunks, int):
            total_chunks += chunks

    print(f"\n  Total chunks indexed to ChromaDB: {total_chunks}")

    # ── Per-file summaries ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  DOCUMENT SUMMARIES")
    print("=" * 70)
    for r in results:
        if r.get("status") == "COMPLETED" and r.get("summary"):
            s = r["summary"]
            print(f"\n  📄 {r['filename']}")
            print(f"     Title       : {s.get('title', '—')}")
            print(f"     Type        : {s.get('document_type', '—')}")
            print(f"     Summary     : {s.get('summary', '—')[:200]}")
            kp = s.get("key_points", [])
            if kp:
                print(f"     Key Points  : {kp[0][:100]}")
                for k in kp[1:3]:
                    print(f"                   {k[:100]}")
        elif r.get("status") != "COMPLETED":
            print(f"\n  ✗ {r['filename']}  →  {r.get('error','unknown error')[:200]}")

    print("\n" + "=" * 70)
    print(f"  Done. Job IDs saved below for RAG queries / RAGAS evaluation.")
    print("=" * 70)
    for r in results:
        if r.get("status") == "COMPLETED":
            print(f"  {r['filename'][:45]}  →  job_id: {r['job_id']}")

    print()


if __name__ == "__main__":
    main()

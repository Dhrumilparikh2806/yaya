"""Debug script - run one job directly to find crash cause."""
import sys
import os
sys.path.insert(0, ".")
os.chdir(r"C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag")

from dotenv import load_dotenv
load_dotenv(".env")

from app.config import settings
from app.models.db import get_engine, Job, JobStatus
from sqlmodel import Session, select
from pathlib import Path

with Session(get_engine()) as db:
    # Get first PROCESSING job
    job = db.exec(select(Job).where(Job.status == JobStatus.processing).limit(1)).first()
    if not job:
        job = db.exec(select(Job).where(Job.status == JobStatus.pending).limit(1)).first()

    if not job:
        print("No jobs found")
        sys.exit(1)

    print(f"Job     : {job.filename} ({job.file_type})")
    print(f"Path    : {job.file_path}")
    print(f"Exists  : {Path(job.file_path).exists()}")

    try:
        print("\n--- STEP 1: Extract ---")
        if job.file_type == "pdf":
            from app.processors.pdf import PDFProcessor
            p = PDFProcessor(job=job, settings=settings)
        elif job.file_type == "docx":
            from app.processors.docx_proc import DOCXProcessor
            p = DOCXProcessor(job=job, settings=settings)
        elif job.file_type in ("xlsx", "csv"):
            from app.processors.xlsx_proc import XLSXProcessor
            p = XLSXProcessor(job=job, settings=settings)
        elif job.file_type == "image":
            from app.processors.image import ImageProcessor
            p = ImageProcessor(job=job, settings=settings)

        text = p.extract()
        print(f"Extract OK: {len(text)} chars")

        print("\n--- STEP 2: Summarise (Groq) ---")
        summary = p.summarise(text, db)
        print(f"Summarise OK: {list(summary.keys())}")

        print("\n--- STEP 3: Chunk ---")
        from app.rag.chunker import chunk_text
        chunks = chunk_text(text, job_id=str(job.id), filename=job.filename,
                            file_type=job.file_type, chunk_size=settings.CHUNK_SIZE,
                            overlap=settings.CHUNK_OVERLAP)
        print(f"Chunks: {len(chunks)}")

        print("\n--- STEP 4: Embed (local) ---")
        from app.rag.embedder import embed_chunks
        embeddings = embed_chunks(chunks, job.user_id, job.id, settings, db)
        print(f"Embeddings: {len(embeddings)} x {len(embeddings[0])} dims")

        print("\n--- STEP 5: Index ChromaDB ---")
        from app.rag.vectorstore import get_chroma_client, get_or_create_collection, add_chunks, delete_job_chunks
        client = get_chroma_client(settings)
        collection = get_or_create_collection(client, settings)
        delete_job_chunks(collection, str(job.id))
        add_chunks(collection, chunks, embeddings)
        print(f"Indexed OK")

        print("\nALL STEPS PASSED")

    except Exception as e:
        import traceback
        print(f"\nCRASH AT STEP: {e}")
        traceback.print_exc()

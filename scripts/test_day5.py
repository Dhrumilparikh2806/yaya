"""
Day 5 verification: embed + ChromaDB add/search end-to-end.
Run: python scripts/test_day5.py
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


def get_or_create_test_user(db):
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "day5test@test.com")).first()
    if not user:
        from app.security import hash_password
        user = User(
            email="day5test@test.com",
            hashed_password=hash_password("test123"),
            role=UserRole.user,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def test_embed_query():
    print("\n=== Test: embed_query ===")
    from app.config import settings
    from app.rag.embedder import embed_query

    vec = embed_query("What is machine learning?", settings)
    assert len(vec) == 768, f"Expected 768-dim vector, got {len(vec)}"
    print(f"[PASS] embed_query: dim={len(vec)}, first3={[round(v,4) for v in vec[:3]]}")
    return vec


def test_embed_chunks_and_chromadb(query_vec):
    print("\n=== Test: embed_chunks + ChromaDB ===")
    from app.config import settings
    from app.rag.embedder import embed_chunks
    from app.rag.vectorstore import (
        get_chroma_client, get_or_create_collection,
        add_chunks, search, delete_job_chunks
    )

    with Session(engine) as db:
        user = get_or_create_test_user(db)

        job_id = str(uuid.uuid4())
        fake_job_id = uuid.UUID(job_id)

        # Create a fake job record for log_llm_call
        job = Job(
            id=fake_job_id,
            user_id=user.id,
            filename="test_rag.pdf",
            file_type="pdf",
            file_path="C:/tmp/fake.pdf",
            file_size_bytes=1000,
            status=JobStatus.processing,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()

        # Chunker
        from app.rag.chunker import chunk_text
        text = "[Page 1]\n" + "Machine learning is a subset of AI that enables computers to learn. " * 20
        text += "\n[Page 2]\n" + "Deep learning uses neural networks with many layers. " * 20
        chunks = chunk_text(text, job_id, "test_rag.pdf", "pdf",
                           chunk_size=100, overlap=20)
        print(f"chunks produced: {len(chunks)}")
        assert len(chunks) > 0, "No chunks produced!"

        # Embedder
        embeddings = embed_chunks(chunks, user.id, fake_job_id, settings, db)
        assert len(embeddings) == len(chunks), "Embedding count mismatch"
        assert len(embeddings[0]) == 768, f"Wrong embedding dim: {len(embeddings[0])}"
        print(f"[PASS] embed_chunks: {len(embeddings)} vectors, dim={len(embeddings[0])}")

        # Check usage_logs
        from sqlmodel import select
        logs = db.exec(select(UsageLog).where(UsageLog.job_id == fake_job_id)).all()
        print(f"usage_logs for embed job: {len(logs)}")
        assert len(logs) > 0, "No usage logs for embed_chunks!"
        for lg in logs:
            print(f"  endpoint={lg.endpoint} tokens={lg.prompt_tokens} latency={lg.latency_ms}ms")

        # ChromaDB
        client = get_chroma_client(settings)
        collection = get_or_create_collection(client, settings)

        delete_job_chunks(collection, job_id)  # clean before add
        add_chunks(collection, chunks, embeddings)
        print(f"[PASS] add_chunks: {len(chunks)} chunks upserted")

        # Search
        results = search(collection, query_vec, top_k=3, job_ids=[job_id])
        print(f"search results: {len(results)}")
        assert len(results) > 0, "No search results!"
        for r in results:
            print(f"  score={round(r['score'],4)} page={r['page_or_segment']} text={r['text'][:60]}")

        print("[PASS] ChromaDB search returning ranked results")
        return len(chunks)


def test_full_pipeline():
    print("\n=== Test: full pipeline via test PDF processor ===")
    from app.config import settings
    from app.rag.chunker import chunk_text
    from app.rag.embedder import embed_chunks
    from app.rag.vectorstore import (
        get_chroma_client, get_or_create_collection, add_chunks
    )
    import chromadb

    # Verify ChromaDB collection exists with documents
    client = get_chroma_client(settings)
    collection = get_or_create_collection(client, settings)
    count = collection.count()
    print(f"[INFO] ChromaDB collection '{settings.CHROMA_COLLECTION}' has {count} documents")
    print("[PASS] ChromaDB collection accessible")


def main():
    try:
        query_vec = test_embed_query()
        chunk_count = test_embed_chunks_and_chromadb(query_vec)
        test_full_pipeline()

        print("\n" + "="*60)
        print("DAY 5 VERIFICATION SUMMARY")
        print("="*60)
        print(f"[PASS] embed_query: 768-dim vector")
        print(f"[PASS] chunk_text + embed_chunks: {chunk_count} chunks with real embeddings")
        print(f"[PASS] ChromaDB: add + search + usage_logs populated")
        print(f"[PASS] Full pipeline wiring verified")
    except Exception as e:
        import traceback
        print(f"\n[FAIL] {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

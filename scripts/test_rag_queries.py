"""Quick RAG retrieval smoke test before RAGAS eval."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

from sqlmodel import Session, create_engine, select
from app.config import settings
from app.rag import engine as rag_engine
from app.models.db import User
import os

db_engine = create_engine(os.environ["DATABASE_URL"], echo=False)

QUESTIONS = [
    "What sales deals or opportunities are currently being tracked?",
    "Who are the key contacts or customers in the CRM?",
    "What are the revenue forecasts for 2026?",
    "What support tickets have been raised and what is their status?",
    "What products or services are mentioned in the documents?",
]

with Session(db_engine) as db:
    user = db.exec(select(User)).first()
    if not user:
        print("ERROR: No users in database")
        sys.exit(1)
    print(f"Querying as user: {user.email}\n")

    for q in QUESTIONS:
        print(f"Q: {q}")
        try:
            result = rag_engine.query(
                question=q,
                job_ids=None,
                user_id=user.id,
                db=db,
                settings=settings,
            )
            gate = result.get("confidence_gate_passed", False)
            score = result.get("avg_similarity_score", 0)
            chunks = result.get("citations", [])
            answer = result.get("answer", "")
            print(f"   Gate: {'PASS' if gate else 'FAIL'}  Score: {score:.3f}  Chunks: {len(chunks)}")
            print(f"   Sources: {[c['filename'] for c in chunks[:3]]}")
            print(f"   Answer: {answer[:200]}")
        except Exception as e:
            print(f"   ERROR: {e}")
        print()

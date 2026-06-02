"""Interactive NLP demo — shows full answer + citations for each question."""
import sys, json
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
    "What deals are we close to closing and what are the deal values?",
    "Which clients have open support tickets with high priority?",
    "What is the onboarding plan for Sterling Capital Bank?",
    "What are the revenue forecasts for BlueSky Retail Group in 2026?",
    "Who should I contact at Acme Corporation and what is their email?",
]

SEP = "=" * 70

with Session(db_engine) as db:
    user = db.exec(select(User)).first()

    for q in QUESTIONS:
        print(f"\n{SEP}")
        print(f"QUESTION: {q}")
        print(SEP)

        result = rag_engine.query(
            question=q,
            job_ids=None,
            user_id=user.id,
            db=db,
            settings=settings,
        )

        gate = result.get("confidence_gate_passed", False)
        score = result.get("avg_similarity_score", 0)
        answer = result.get("answer", "")
        citations = result.get("citations", [])

        print(f"Confidence: {score:.3f}  |  Gate: {'PASS' if gate else 'FAIL'}")
        print(f"\nANSWER:\n{answer}")

        if citations:
            print(f"\nSOURCES ({len(citations)}):")
            for c in citations:
                print(f"  [{c['index']}] {c['filename']} — {c['page_or_segment']}")
                print(f"       {c['excerpt'][:120]}...")

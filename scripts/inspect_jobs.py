"""Sample job results to build accurate RAGAS ground truths."""
import sys, json
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

from sqlmodel import Session, create_engine, text
import os

engine = create_engine(os.environ["DATABASE_URL"], echo=False)
with Session(engine) as db:
    # Sample one file of each type
    for ftype in ["pdf", "docx", "xlsx", "image"]:
        rows = db.exec(
            text(f"SELECT filename, result FROM jobs WHERE file_type='{ftype}' AND status='completed' AND result IS NOT NULL LIMIT 2")
        ).fetchall()
        for filename, result in rows:
            try:
                r = json.loads(result)
                print(f"\n=== {filename} ({ftype}) ===")
                print(f"Title: {r.get('title','')}")
                print(f"Summary: {r.get('summary','')}")
                if "key_insights" in r:
                    for ins in r.get("key_insights", [])[:2]:
                        print(f"  - {ins}")
            except Exception:
                pass

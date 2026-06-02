"""Dev utility — re-enqueue all PENDING or FAILED jobs through process_file."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

from app.models.db import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text("SELECT id FROM jobs WHERE status = 'pending'")).fetchall()
    job_ids = [str(r[0]) for r in rows]

print(f"Found {len(job_ids)} pending jobs")

from app.workers.tasks import process_file

for i, jid in enumerate(job_ids):
    process_file.delay(jid)
    if (i + 1) % 20 == 0:
        print(f"  Queued {i+1}/{len(job_ids)}...")

print(f"Done — queued {len(job_ids)} jobs to Celery")

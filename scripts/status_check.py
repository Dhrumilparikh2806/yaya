"""Dev utility — quick health summary: service status, job counts, chunk counts."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

from app.models.db import get_engine
from sqlalchemy import text
import redis

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text("SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status")).fetchall()
    total = sum(r[1] for r in rows)
    print(f"Job status (total={total}):")
    for r in rows:
        print(f"  {r[0]}: {r[1]}")

    # Show current processing step
    proc = conn.execute(text("SELECT step, COUNT(*) FROM jobs WHERE status='processing' GROUP BY step")).fetchall()
    if proc:
        print("  Processing steps:")
        for r in proc:
            print(f"    {r[0]}: {r[1]}")

    # Sample recent failures
    fails = conn.execute(text(
        "SELECT filename, status, error_type, LEFT(error_message, 150) FROM jobs WHERE status IN ('failed','failed_permanent') ORDER BY updated_at DESC LIMIT 5"
    )).fetchall()
    if fails:
        print("\nRecent failures:")
        for r in fails:
            print(f"  [{r[0]}] {r[1]} | {r[2]}")
            print(f"    {r[3]}")

r = redis.Redis.from_url("redis://localhost:6379/0")
print(f"\nRedis celery queue: {r.llen('celery')}")

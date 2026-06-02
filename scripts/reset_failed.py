"""Dev utility — reset FAILED / FAILED_PERMANENT jobs back to PENDING for retry."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

from app.models.db import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    result = conn.execute(text(
        "UPDATE jobs SET status='pending', step=NULL, retry_count=0, "
        "error_type=NULL, error_message=NULL, updated_at=NOW() "
        "WHERE status IN ('failed', 'failed_permanent', 'processing')"
    ))
    conn.commit()
    print(f"Reset {result.rowcount} jobs to pending")
    rows = conn.execute(text("SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status")).fetchall()
    for r in rows:
        print(f"  {r[0]}: {r[1]}")

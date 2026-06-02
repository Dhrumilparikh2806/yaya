"""Dev utility — print error_type and error_message for all failed jobs."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

from app.models.db import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT filename, status, updated_at, error_message FROM jobs WHERE status IN ('failed','failed_permanent') ORDER BY updated_at DESC"
    )).fetchall()
    for r in rows:
        print(f"\n[{r[0]}] {r[1]} @ {r[2]}")
        print(r[3])

"""Dev utility — repeatedly poll job status until all jobs reach a terminal state."""
import time
import sys

sys.path.insert(0, ".")

from app.models.db import get_engine, Job, JobStatus
from sqlmodel import Session, select, func

engine = get_engine()
for i in range(180):
    with Session(engine) as db:
        rows = db.exec(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
    by_status = {s: c for s, c in rows}
    completed = by_status.get(JobStatus.completed, 0)
    processing = by_status.get(JobStatus.processing, 0)
    pending = by_status.get(JobStatus.pending, 0)
    failed = by_status.get(JobStatus.failed, 0) + by_status.get(JobStatus.failed_permanent, 0)
    print(f"  completed={completed} pending={pending} processing={processing} failed={failed}", flush=True)
    if pending == 0 and processing == 0:
        print("ALL DONE")
        break
    time.sleep(30)
else:
    print("TIMEOUT")

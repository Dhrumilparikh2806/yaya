"""Dev utility — purge all pending tasks from the Celery Redis queue."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
import redis

r = redis.Redis.from_url("redis://localhost:6379/0")
before = r.llen("celery")
r.delete("celery")
after = r.llen("celery")
print(f"Flushed Redis celery queue: {before} -> {after} items")

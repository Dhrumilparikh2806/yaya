"""
Celery application instance and broker/backend configuration.

Broker  — Redis (fast, ephemeral task queue).
Backend — PostgreSQL via SQLAlchemy (durable task-result storage).

task_acks_late=True    — the task message is not acknowledged until the task
                         finishes, preventing duplicate processing if the worker
                         crashes mid-run and Redis redelivers the message.
worker_prefetch_multiplier=1 — each worker fetches one task at a time, which
                               is important because process_file can be slow
                               (minutes for large audio/video files).

A daily beat schedule runs cleanup_old_uploads to delete uploaded files for
jobs that completed or permanently failed more than 7 days ago.
"""

from celery import Celery
from app.config import settings

celery_app = Celery(
    "geminirag",
    broker=settings.REDIS_URL,
    backend="db+" + settings.DATABASE_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "cleanup-old-uploads-daily": {
            "task": "app.workers.tasks.cleanup_old_uploads",
            "schedule": 86400,  # every 24 hours
        },
    },
)

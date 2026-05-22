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

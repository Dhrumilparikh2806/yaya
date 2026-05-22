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
)

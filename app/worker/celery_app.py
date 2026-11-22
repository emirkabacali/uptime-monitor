"""Celery application: Redis is the message broker.

Run:
    celery -A app.worker.celery_app worker --pool=threads --concurrency=20
    celery -A app.worker.celery_app beat      # exactly ONE beat instance
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("uptime_monitor", broker=settings.redis_url, include=["app.worker.tasks"])

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    # Results are written to PostgreSQL by the tasks themselves.
    task_ignore_result=True,
    # Acknowledge a message only after the task finished. If a worker dies in
    # the middle, the message is delivered again (at-least-once delivery), so
    # tasks must be safe to run twice (idempotent).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # A worker takes one message at a time per thread, so slow checks do not
    # hold back messages that another thread could process.
    worker_prefetch_multiplier=1,
    # A check has its own HTTP timeout (max 30s, up to 6 hops); this is a safety net.
    task_soft_time_limit=200,
    task_time_limit=240,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-checks": {
            "task": "app.worker.tasks.dispatch_due_checks",
            "schedule": 10.0,  # seconds
            # A dispatch that waited longer than one period is useless: skip it.
            "options": {"expires": 10},
        },
        "cleanup-old-checks": {
            "task": "app.worker.tasks.cleanup_old_checks",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

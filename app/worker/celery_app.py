"""Celery application: Redis is the message broker.

Run:
    celery -A app.worker.celery_app worker --pool=threads --concurrency=20
    celery -A app.worker.celery_app beat      # exactly ONE beat instance
"""

import logging
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    task_postrun,
    task_prerun,
    worker_init,
)
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import configure_logging, task_id_var

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


@after_setup_logger.connect
@after_setup_task_logger.connect
def _json_logging(**_: object) -> None:
    configure_logging()


@task_prerun.connect
def _bind_task_id(task_id: str | None = None, **_: object) -> None:
    # Every log line written while this task runs carries its task_id.
    task_id_var.set(task_id)


@task_postrun.connect
def _unbind_task_id(**_: object) -> None:
    task_id_var.set(None)


@worker_init.connect
def _start_metrics_server(**_: object) -> None:
    """Expose worker metrics for Prometheus (the worker has no web server of its own).

    The thread pool runs every task inside this one process, so all threads
    update the same in-memory counters and one endpoint shows the full picture.
    """
    port = int(os.environ.get("WORKER_METRICS_PORT", "9101"))
    start_http_server(port)
    logging.getLogger(__name__).info("Worker metrics listening", extra={"port": port})

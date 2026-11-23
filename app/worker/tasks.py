"""Background tasks: dispatch due checks, run checks, clean up old results.

The logic lives in plain functions that receive a SQLAlchemy session, so tests
can call them directly. The Celery tasks are thin wrappers around them.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.metrics import CHECK_DURATION, CHECKS, MONITORS_ACTIVE, NOTIFICATIONS
from app.db.session import SessionLocal
from app.models import CheckResult, Incident, Monitor, User
from app.services.checker import CheckOutcome, check_url
from app.services.monitor_state import IncidentAction, Transition, next_state
from app.services.notifier import (
    NotificationError,
    format_down_message,
    format_recovered_message,
    get_notifier,
)
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

Checker = Callable[[str, float], CheckOutcome]


# ---------------------------------------------------------------- dispatch


def claim_due_monitors(db: Session, limit: int) -> list[int]:
    """Select due monitors, move their next_check_at forward, return their ids.

    `FOR UPDATE SKIP LOCKED` locks the selected rows. A second dispatcher running
    at the same time skips locked rows instead of waiting, so the same monitor is
    never claimed twice. After commit, next_check_at is in the future, so the
    monitor is not due anymore.
    """
    ids = list(
        db.scalars(
            select(Monitor.id)
            .where(Monitor.is_active.is_(True), Monitor.next_check_at <= func.now())
            .order_by(Monitor.next_check_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if ids:
        db.execute(
            update(Monitor)
            .where(Monitor.id.in_(ids))
            .values(
                next_check_at=func.now()
                + func.make_interval(0, 0, 0, 0, 0, 0, Monitor.interval_seconds)
            )
        )
    db.commit()
    return ids


@celery_app.task(name="app.worker.tasks.dispatch_due_checks")
def dispatch_due_checks() -> int:
    with SessionLocal() as db:
        ids = claim_due_monitors(db, get_settings().dispatch_batch_size)
        MONITORS_ACTIVE.set(
            db.scalar(select(func.count()).select_from(Monitor).where(Monitor.is_active)) or 0
        )
    for monitor_id in ids:
        check_monitor.delay(monitor_id)
    if ids:
        logger.info("Dispatched checks", extra={"count": len(ids)})
    return len(ids)


# ---------------------------------------------------------------- check


@dataclass(frozen=True)
class CheckRun:
    """What happened in one check, used by the caller (e.g. to send alerts)."""

    monitor_id: int
    outcome: CheckOutcome
    transition: Transition
    incident_id: int | None


def _recently_checked(monitor: Monitor, now: datetime) -> bool:
    """True if a check already ran in the first half of the current interval.

    With at-least-once delivery the same task can be delivered twice. This
    guard turns the duplicate into a no-op instead of a second data point.
    """
    if monitor.last_checked_at is None:
        return False
    return now - monitor.last_checked_at < timedelta(seconds=monitor.interval_seconds / 2)


def run_check(db: Session, monitor_id: int, checker: Checker = check_url) -> CheckRun | None:
    """Check one monitor and apply the result. Returns None if skipped."""
    monitor = db.get(Monitor, monitor_id)
    if monitor is None or not monitor.is_active:
        return None  # deleted or paused after it was dispatched
    if _recently_checked(monitor, datetime.now(UTC)):
        logger.info("Skipping duplicate check", extra={"monitor_id": monitor_id})
        return None
    url, timeout = monitor.url, monitor.timeout_seconds
    # End the read transaction: no locks or open transaction during the HTTP call.
    db.commit()

    started = time.perf_counter()
    outcome = checker(url, timeout)  # validates the URL (SSRF) before every request
    CHECK_DURATION.observe(time.perf_counter() - started)
    CHECKS.labels(result="up" if outcome.is_up else "down").inc()
    now = datetime.now(UTC)

    # Lock the monitor row so two checks of the same monitor cannot interleave
    # and corrupt the counters.
    monitor = db.scalar(select(Monitor).where(Monitor.id == monitor_id).with_for_update())
    if monitor is None or not monitor.is_active:
        db.rollback()
        return None
    if _recently_checked(monitor, now):
        db.rollback()
        return None

    db.add(
        CheckResult(
            monitor_id=monitor_id,
            checked_at=now,
            is_up=outcome.is_up,
            status_code=outcome.status_code,
            response_time_ms=outcome.response_time_ms,
            error=outcome.error,
        )
    )
    transition = next_state(
        monitor.status,
        monitor.consecutive_failures,
        outcome.is_up,
        get_settings().failure_threshold,
    )
    monitor.status = transition.status
    monitor.consecutive_failures = transition.consecutive_failures
    monitor.last_checked_at = now

    incident_id: int | None = None
    if transition.incident_action is IncidentAction.OPEN:
        # ON CONFLICT DO NOTHING on the partial unique index: if an open incident
        # already exists, nothing happens instead of an error.
        incident_id = db.scalar(
            insert(Incident)
            .values(monitor_id=monitor_id, started_at=now, cause=outcome.error or "unknown")
            .on_conflict_do_nothing(
                index_elements=["monitor_id"], index_where=text("resolved_at IS NULL")
            )
            .returning(Incident.id)
        )
    elif transition.incident_action is IncidentAction.RESOLVE:
        incident_id = db.scalar(
            update(Incident)
            .where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None))
            .values(resolved_at=now)
            .returning(Incident.id)
        )
    db.commit()

    if transition.incident_action is not IncidentAction.NONE:
        logger.info(
            "Monitor changed state",
            extra={"monitor_id": monitor_id, "status": transition.status.value},
        )
    return CheckRun(monitor_id, outcome, transition, incident_id)


def build_notification(db: Session, run: CheckRun) -> tuple[str, str] | None:
    """Return (chat_id, text) when the state changed, else None.

    Only state CHANGES are notified: DOWN once when the incident opens, and
    RECOVERED once when it is resolved. Nothing while it stays down.
    """
    if run.transition.incident_action is IncidentAction.NONE or run.incident_id is None:
        return None
    row = db.execute(
        select(Monitor.name, Monitor.url, User.telegram_chat_id, Incident)
        .join(User, User.id == Monitor.user_id)
        .join(Incident, Incident.monitor_id == Monitor.id)
        .where(Monitor.id == run.monitor_id, Incident.id == run.incident_id)
    ).one_or_none()
    if row is None or not row.telegram_chat_id:
        return None
    incident = row.Incident
    if run.transition.incident_action is IncidentAction.OPEN:
        text = format_down_message(row.name, row.url, incident.cause, incident.started_at)
    else:
        downtime = (incident.resolved_at or datetime.now(UTC)) - incident.started_at
        text = format_recovered_message(row.name, row.url, downtime)
    return row.telegram_chat_id, text


@celery_app.task(name="app.worker.tasks.check_monitor")
def check_monitor(monitor_id: int) -> None:
    with SessionLocal() as db:
        run = run_check(db, monitor_id)
        message = build_notification(db, run) if run is not None else None
    if message is not None:
        try:
            send_notification.delay(*message)
        except Exception:
            # A failure to enqueue the alert must not break the check itself.
            logger.exception("Could not enqueue notification", extra={"monitor_id": monitor_id})


# ---------------------------------------------------------------- notify


@celery_app.task(
    name="app.worker.tasks.send_notification",
    autoretry_for=(NotificationError,),
    max_retries=5,
    retry_backoff=True,  # wait 1s, 2s, 4s, 8s, 16s ... between attempts
    retry_backoff_max=600,
    retry_jitter=True,  # randomize waits so many retries do not hit Telegram together
)
def send_notification(chat_id: str, text: str) -> str:
    notifier = get_notifier()
    if notifier is None:
        logger.info("Notifications disabled (no TELEGRAM_BOT_TOKEN), skipping")
        NOTIFICATIONS.labels(status="skipped").inc()
        return "skipped"
    try:
        notifier.send(chat_id, text)
    except NotificationError:
        NOTIFICATIONS.labels(status="failed").inc()  # counted per attempt; Celery retries
        raise
    NOTIFICATIONS.labels(status="sent").inc()
    return "sent"


# ---------------------------------------------------------------- cleanup


def delete_old_checks(db: Session, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = db.execute(delete(CheckResult).where(CheckResult.checked_at < cutoff))
    db.commit()
    return result.rowcount or 0


@celery_app.task(name="app.worker.tasks.cleanup_old_checks")
def cleanup_old_checks() -> int:
    with SessionLocal() as db:
        deleted = delete_old_checks(db, get_settings().check_retention_days)
    logger.info("Deleted old check results", extra={"count": deleted})
    return deleted

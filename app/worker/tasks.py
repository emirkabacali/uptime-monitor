"""Background tasks: dispatch due checks, run checks, clean up old results.

The logic lives in plain functions that receive a SQLAlchemy session, so tests
can call them directly. The Celery tasks are thin wrappers around them.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CheckResult, Incident, Monitor
from app.services.checker import CheckOutcome, check_url
from app.services.monitor_state import IncidentAction, Transition, next_state
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

    outcome = checker(url, timeout)  # validates the URL (SSRF) before every request
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


@celery_app.task(name="app.worker.tasks.check_monitor")
def check_monitor(monitor_id: int) -> None:
    with SessionLocal() as db:
        run_check(db, monitor_id)


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

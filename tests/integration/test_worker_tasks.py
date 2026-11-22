"""Worker task logic, called directly as functions (network mocked)."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.models import CheckResult, Incident, Monitor, MonitorStatus, User
from app.services.checker import CheckOutcome
from app.worker import tasks

UP = CheckOutcome(is_up=True, status_code=200, response_time_ms=50, error=None)
DOWN = CheckOutcome(is_up=False, status_code=None, response_time_ms=None, error="timeout")


def make_monitor(db: Session, **fields) -> Monitor:
    user = db.scalar(select(User).where(User.email == "worker@example.com"))
    if user is None:
        user = User(email="worker@example.com", hashed_password="!")
        db.add(user)
        db.flush()
    values = {"name": "m", "url": "https://example.com/", "next_check_at": func.now()} | fields
    monitor = Monitor(user_id=user.id, **values)
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def run(db: Session, monitor_id: int, outcome: CheckOutcome) -> tasks.CheckRun | None:
    """Run one check as if a full interval had passed since the previous one."""
    db.execute(
        update(Monitor)
        .where(Monitor.id == monitor_id, Monitor.last_checked_at.is_not(None))
        .values(last_checked_at=Monitor.last_checked_at - timedelta(hours=1))
    )
    db.commit()
    return tasks.run_check(db, monitor_id, checker=lambda url, timeout: outcome)


def incidents(db: Session, monitor_id: int) -> list[Incident]:
    return list(db.scalars(select(Incident).where(Incident.monitor_id == monitor_id)))


# ------------------------------------------------------------------ dispatch


def test_claims_only_due_active_monitors(db_session: Session) -> None:
    due = make_monitor(db_session)
    future = make_monitor(db_session, next_check_at=datetime.now(UTC) + timedelta(minutes=5))
    paused = make_monitor(db_session, is_active=False)

    claimed = tasks.claim_due_monitors(db_session, limit=100)

    assert due.id in claimed
    assert future.id not in claimed
    assert paused.id not in claimed


def test_claim_moves_next_check_forward(db_session: Session) -> None:
    monitor = make_monitor(db_session, interval_seconds=120)

    tasks.claim_due_monitors(db_session, limit=100)
    db_session.refresh(monitor)

    delay = monitor.next_check_at - datetime.now(UTC)
    assert timedelta(seconds=110) < delay <= timedelta(seconds=121)
    # Not due anymore: a second dispatch does not claim it again.
    assert monitor.id not in tasks.claim_due_monitors(db_session, limit=100)


def test_claim_respects_batch_limit(db_session: Session) -> None:
    for _ in range(3):
        make_monitor(db_session)

    assert len(tasks.claim_due_monitors(db_session, limit=2)) == 2


def test_concurrent_dispatchers_never_claim_the_same_monitor(engine: Engine) -> None:
    """Two dispatchers at the same moment: SKIP LOCKED gives each row to only one."""
    with Session(engine) as setup:
        user = User(email="concurrent@example.com", hashed_password="!")
        setup.add(user)
        setup.flush()
        monitor = Monitor(user_id=user.id, name="c", url="https://example.com/")
        setup.add(monitor)
        setup.commit()
        user_id, monitor_id = user.id, monitor.id
    try:
        with Session(engine) as first, Session(engine) as second:
            # First dispatcher selects and locks, but has not committed yet.
            locked = list(
                first.scalars(
                    select(Monitor.id)
                    .where(Monitor.id == monitor_id, Monitor.next_check_at <= func.now())
                    .with_for_update(skip_locked=True)
                )
            )
            # Second dispatcher runs meanwhile: the locked row is skipped, no waiting.
            claimed_by_second = tasks.claim_due_monitors(second, limit=500)
            first.rollback()

        assert locked == [monitor_id]
        assert monitor_id not in claimed_by_second
    finally:
        with Session(engine) as cleanup:
            cleanup.delete(cleanup.get(User, user_id))
            cleanup.commit()


def test_dispatch_task_enqueues_one_check_per_monitor(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = make_monitor(db_session), make_monitor(db_session)
    queued: list[int] = []

    @contextmanager
    def session_factory():
        yield db_session

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks.check_monitor, "delay", queued.append)

    count = tasks.dispatch_due_checks()

    assert count == len(queued) >= 2
    assert {first.id, second.id} <= set(queued)


# ------------------------------------------------------------------ check


def test_successful_check_saves_result_and_sets_up(db_session: Session) -> None:
    monitor = make_monitor(db_session)

    result = run(db_session, monitor.id, UP)
    db_session.refresh(monitor)

    assert result is not None
    assert monitor.status is MonitorStatus.UP
    assert monitor.last_checked_at is not None
    saved = db_session.scalars(
        select(CheckResult).where(CheckResult.monitor_id == monitor.id)
    ).all()
    assert [(c.is_up, c.status_code, c.response_time_ms) for c in saved] == [(True, 200, 50)]


def test_down_after_threshold_opens_exactly_one_incident(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    run(db_session, monitor.id, UP)

    for _ in range(2):
        run(db_session, monitor.id, DOWN)
    db_session.refresh(monitor)
    assert monitor.status is MonitorStatus.UP  # 2 failures: not down yet
    assert incidents(db_session, monitor.id) == []

    third = run(db_session, monitor.id, DOWN)
    run(db_session, monitor.id, DOWN)  # still down: no second incident
    db_session.refresh(monitor)

    assert third is not None and third.transition.status_changed_to_down
    assert monitor.status is MonitorStatus.DOWN
    assert monitor.consecutive_failures == 4
    open_incidents = incidents(db_session, monitor.id)
    assert len(open_incidents) == 1
    assert open_incidents[0].cause == "timeout"
    assert open_incidents[0].resolved_at is None


def test_recovery_resolves_incident(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    for _ in range(3):
        run(db_session, monitor.id, DOWN)

    result = run(db_session, monitor.id, UP)
    db_session.refresh(monitor)

    assert result is not None and result.transition.status_changed_to_up
    assert monitor.status is MonitorStatus.UP
    assert monitor.consecutive_failures == 0
    [incident] = incidents(db_session, monitor.id)
    assert incident.resolved_at is not None
    assert result.incident_id == incident.id


def test_existing_open_incident_does_not_cause_error(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    db_session.add(Incident(monitor_id=monitor.id, started_at=datetime.now(UTC), cause="old"))
    db_session.commit()

    for _ in range(3):
        run(db_session, monitor.id, DOWN)

    assert len(incidents(db_session, monitor.id)) == 1


def test_duplicate_delivery_is_ignored(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    check = lambda url, timeout: UP  # noqa: E731

    first = tasks.run_check(db_session, monitor.id, checker=check)
    second = tasks.run_check(db_session, monitor.id, checker=check)  # same task delivered again

    assert first is not None
    assert second is None
    count = db_session.scalar(
        select(func.count()).select_from(CheckResult).where(CheckResult.monitor_id == monitor.id)
    )
    assert count == 1


def test_paused_or_deleted_monitor_is_skipped(db_session: Session) -> None:
    paused = make_monitor(db_session, is_active=False)

    assert run(db_session, paused.id, UP) is None
    assert run(db_session, 987654321, UP) is None


def test_check_monitor_task_uses_its_own_session(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = make_monitor(db_session)

    @contextmanager
    def session_factory():
        yield db_session

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "check_url", lambda url, timeout: UP)
    monkeypatch.setattr(tasks.run_check, "__defaults__", (tasks.check_url,))

    tasks.check_monitor(monitor.id)
    db_session.refresh(monitor)

    assert monitor.status is MonitorStatus.UP


# ------------------------------------------------------------------ cleanup


def test_cleanup_deletes_only_old_results(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    now = datetime.now(UTC)
    for age_days in (31, 29, 0):
        db_session.add(
            CheckResult(
                monitor_id=monitor.id, checked_at=now - timedelta(days=age_days), is_up=True
            )
        )
    db_session.commit()

    deleted = tasks.delete_old_checks(db_session, retention_days=30)

    remaining = db_session.scalars(
        select(CheckResult.checked_at).where(CheckResult.monitor_id == monitor.id)
    ).all()
    assert deleted == 1
    assert len(remaining) == 2
    assert all(now - checked_at < timedelta(days=30) for checked_at in remaining)

"""Database-level rules that the migration must create."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Incident, Monitor, User


def make_monitor(db: Session) -> Monitor:
    user = User(email="schema@example.com", hashed_password="!")
    db.add(user)
    db.flush()
    monitor = Monitor(user_id=user.id, name="m", url="https://example.com")
    db.add(monitor)
    db.flush()
    return monitor


def test_only_one_open_incident_per_monitor(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    now = datetime.now(UTC)
    db_session.add(Incident(monitor_id=monitor.id, started_at=now, cause="timeout"))
    db_session.flush()

    db_session.add(Incident(monitor_id=monitor.id, started_at=now, cause="timeout"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resolved_incidents_do_not_block_new_ones(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    now = datetime.now(UTC)
    db_session.add(
        Incident(monitor_id=monitor.id, started_at=now, resolved_at=now, cause="timeout")
    )
    db_session.add(Incident(monitor_id=monitor.id, started_at=now, cause="http_500"))

    db_session.flush()  # no error: only one incident is open


def test_deleting_user_cascades_to_monitors(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    user = db_session.get(User, monitor.user_id)
    monitor_id = monitor.id

    db_session.delete(user)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(Monitor, monitor_id) is None

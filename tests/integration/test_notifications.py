"""Alerts are sent only on state changes, with retries, and never break checks."""

from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.main import app
from app.models import Monitor, User
from app.services.checker import CheckOutcome
from app.services.notifier import NotificationError, get_notifier
from app.worker import tasks

UP = CheckOutcome(is_up=True, status_code=200, response_time_ms=50, error=None)
DOWN = CheckOutcome(is_up=False, status_code=None, response_time_ms=None, error="timeout")


class FakeNotifier:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[tuple[str, str]] = []
        self.failures = failures

    def send(self, chat_id: str, text: str) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise NotificationError("temporary failure")
        self.sent.append((chat_id, text))


@pytest.fixture
def worker_env(db_session: Session, monkeypatch: pytest.MonkeyPatch):
    """Run check_monitor against the test session; capture enqueued alerts."""
    queued: list[tuple[str, str]] = []
    results = {"next": UP}

    @contextmanager
    def session_factory():
        yield db_session

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks.run_check, "__defaults__", (lambda url, timeout: results["next"],))
    monkeypatch.setattr(tasks.send_notification, "delay", lambda *args: queued.append(args))
    return queued, results


def make_monitor(db: Session, chat_id: str | None = "555") -> Monitor:
    user = User(email="alerts@example.com", hashed_password="!", telegram_chat_id=chat_id)
    db.add(user)
    db.flush()
    monitor = Monitor(
        user_id=user.id, name="My Site", url="https://example.com/", next_check_at=func.now()
    )
    db.add(monitor)
    db.commit()
    return monitor


def check(db: Session, monitor_id: int, results: dict, outcome: CheckOutcome) -> None:
    """Run the Celery task as if a full interval had passed."""
    db.execute(
        update(Monitor)
        .where(Monitor.id == monitor_id, Monitor.last_checked_at.is_not(None))
        .values(last_checked_at=Monitor.last_checked_at - timedelta(hours=1))
    )
    db.commit()
    results["next"] = outcome
    tasks.check_monitor(monitor_id)


def test_alerts_only_on_state_changes(db_session: Session, worker_env) -> None:
    queued, results = worker_env
    monitor = make_monitor(db_session)

    check(db_session, monitor.id, results, UP)
    check(db_session, monitor.id, results, DOWN)
    check(db_session, monitor.id, results, DOWN)
    assert queued == []  # two failures: no alert yet

    check(db_session, monitor.id, results, DOWN)  # third failure: DOWN
    check(db_session, monitor.id, results, DOWN)  # still down: no repeat
    check(db_session, monitor.id, results, DOWN)
    assert len(queued) == 1
    chat_id, text = queued[0]
    assert chat_id == "555"
    assert text.startswith("🔴 DOWN: My Site (https://example.com/) — timeout")

    check(db_session, monitor.id, results, UP)  # recovered
    check(db_session, monitor.id, results, UP)  # still up: no repeat
    assert len(queued) == 2
    assert queued[1][1].startswith("🟢 RECOVERED: My Site (https://example.com/) — downtime ")


def test_no_alert_without_chat_id(db_session: Session, worker_env) -> None:
    queued, results = worker_env
    monitor = make_monitor(db_session, chat_id=None)

    for _ in range(3):
        check(db_session, monitor.id, results, DOWN)

    assert queued == []
    assert db_session.get(Monitor, monitor.id).status.value == "DOWN"


def test_enqueue_failure_does_not_break_the_check(
    db_session: Session, worker_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, results = worker_env

    def broken_delay(*args):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.send_notification, "delay", broken_delay)
    monitor = make_monitor(db_session)

    for _ in range(3):
        check(db_session, monitor.id, results, DOWN)  # does not raise

    assert db_session.get(Monitor, monitor.id).status.value == "DOWN"


def test_send_notification_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = FakeNotifier(failures=2)
    monkeypatch.setattr(tasks, "get_notifier", lambda: notifier)

    result = tasks.send_notification.apply(args=("555", "hello"))

    assert result.successful()
    assert result.result == "sent"
    assert notifier.sent == [("555", "hello")]


def test_send_notification_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = FakeNotifier(failures=100)
    monkeypatch.setattr(tasks, "get_notifier", lambda: notifier)

    result = tasks.send_notification.apply(args=("555", "hello"))

    assert result.failed()
    assert notifier.failures == 100 - 6  # first attempt + 5 retries


def test_send_notification_uses_exponential_backoff() -> None:
    task = tasks.send_notification
    assert task.max_retries == 5
    assert task.retry_backoff is True
    assert task.retry_jitter is True
    assert NotificationError in task.autoretry_for


def test_send_notification_skips_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "get_notifier", lambda: None)

    assert tasks.send_notification.apply(args=("555", "hello")).result == "skipped"


# ------------------------------------------------------------- test endpoint

TEST_URL = "/api/v1/users/me/test-notification"


def test_test_notification_is_sent(auth_client: TestClient) -> None:
    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    auth_client.patch("/api/v1/users/me", json={"telegram_chat_id": "777"})

    response = auth_client.post(TEST_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    assert notifier.sent[0][0] == "777"
    assert "Test notification" in notifier.sent[0][1]


def test_test_notification_requires_chat_id(auth_client: TestClient) -> None:
    app.dependency_overrides[get_notifier] = lambda: FakeNotifier()

    response = auth_client.post(TEST_URL)

    assert response.status_code == 400
    assert response.json()["code"] == "telegram_chat_id_missing"


def test_test_notification_when_disabled(auth_client: TestClient) -> None:
    app.dependency_overrides[get_notifier] = lambda: None

    response = auth_client.post(TEST_URL)

    assert response.status_code == 503
    assert response.json()["code"] == "notifications_disabled"


def test_test_notification_telegram_failure(auth_client: TestClient) -> None:
    app.dependency_overrides[get_notifier] = lambda: FakeNotifier(failures=1)
    auth_client.patch("/api/v1/users/me", json={"telegram_chat_id": "777"})

    response = auth_client.post(TEST_URL)

    assert response.status_code == 502
    assert response.json()["code"] == "notification_failed"

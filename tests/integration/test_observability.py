import json
import logging
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import JsonFormatter, request_id_var, task_id_var
from app.models import Monitor, User
from app.services.checker import CheckOutcome
from app.services.notifier import NotificationError
from app.worker import tasks


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ------------------------------------------------------------------ request id


def test_response_has_generated_request_id(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32


def test_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})

    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(response.headers["X-Request-ID"]) == 32


def test_request_log_line_has_request_id_and_no_query(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get("/health?token=secret-value", headers={"X-Request-ID": "trace-1"})

    [record] = [r for r in caplog.records if r.name == "app.request"]
    line = json.loads(JsonFormatter().format(record))
    assert response.status_code == 200
    assert line["message"] == "request completed"
    assert line["path"] == "/health"
    assert line["status"] == 200
    assert "secret-value" not in json.dumps(line)


# ------------------------------------------------------------------ JSON logs


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_fields() -> None:
    token = request_id_var.set("req-42")
    try:
        line = json.loads(JsonFormatter().format(make_record(monitor_id=7)))
    finally:
        request_id_var.reset(token)

    assert line["message"] == "hello world"
    assert line["level"] == "INFO"
    assert line["logger"] == "app.test"
    assert line["request_id"] == "req-42"
    assert line["monitor_id"] == 7
    assert line["time"].endswith("+00:00")


def test_json_formatter_includes_task_id() -> None:
    token = task_id_var.set("task-9")
    try:
        line = json.loads(JsonFormatter().format(make_record()))
    finally:
        task_id_var.reset(token)

    assert line["task_id"] == "task-9"


def test_sensitive_extra_fields_are_redacted() -> None:
    line = json.loads(JsonFormatter().format(make_record(password="hunter2", token="t0k3n")))

    assert line["password"] == "[REDACTED]"
    assert line["token"] == "[REDACTED]"


def test_exceptions_are_logged() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = make_record()
        record.exc_info = sys.exc_info()

    line = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in line["exception"]


# ------------------------------------------------------------------ API metrics


def test_metrics_endpoint_uses_route_templates(auth_client: TestClient) -> None:
    before = sample(
        "http_requests_total", method="GET", route="/api/v1/monitors/{monitor_id}", status="404"
    )
    auth_client.get("/api/v1/monitors/123456")
    auth_client.get("/api/v1/monitors/654321")

    body = auth_client.get("/metrics").text

    after = sample(
        "http_requests_total", method="GET", route="/api/v1/monitors/{monitor_id}", status="404"
    )
    assert after - before == 2
    assert "/api/v1/monitors/123456" not in body  # no ids in labels (low cardinality)
    assert "http_request_duration_seconds_bucket" in body


def test_unknown_paths_share_one_label(client: TestClient) -> None:
    before = sample("http_requests_total", method="GET", route="unmatched", status="404")

    client.get("/no/such/path/1")
    client.get("/no/such/path/2")

    assert (
        sample("http_requests_total", method="GET", route="unmatched", status="404") - before == 2
    )


def test_metrics_not_in_openapi(client: TestClient) -> None:
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


# ------------------------------------------------------------------ worker metrics


@pytest.fixture
def worker_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    @contextmanager
    def session_factory():
        yield db_session

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks.check_monitor, "delay", lambda *a: None)
    return db_session


def make_monitor(db: Session, active: bool = True) -> Monitor:
    user = User(email=f"metrics{active}@example.com", hashed_password="!")
    db.add(user)
    db.flush()
    monitor = Monitor(
        user_id=user.id,
        name="m",
        url="https://example.com/",
        next_check_at=func.now(),
        is_active=active,
    )
    db.add(monitor)
    db.commit()
    return monitor


def test_check_metrics(worker_session: Session) -> None:
    monitor = make_monitor(worker_session)
    up_before = sample("uptime_checks_total", result="down")
    count_before = sample("uptime_check_duration_seconds_count")
    outcome = CheckOutcome(is_up=False, status_code=None, response_time_ms=None, error="timeout")

    tasks.run_check(worker_session, monitor.id, checker=lambda url, timeout: outcome)

    assert sample("uptime_checks_total", result="down") - up_before == 1
    assert sample("uptime_check_duration_seconds_count") - count_before == 1


def test_active_monitors_gauge(worker_session: Session) -> None:
    make_monitor(worker_session, active=True)
    make_monitor(worker_session, active=False)

    tasks.dispatch_due_checks()

    assert sample("uptime_monitors_active") >= 1


def test_notification_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class Flaky:
        calls = 0

        def send(self, chat_id: str, text: str) -> None:
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise NotificationError("temporary")

    monkeypatch.setattr(tasks, "get_notifier", lambda: Flaky())
    failed, sent = (
        sample("uptime_notifications_total", status="failed"),
        sample("uptime_notifications_total", status="sent"),
    )

    tasks.send_notification.apply(args=("1", "x"))

    assert sample("uptime_notifications_total", status="failed") - failed == 1
    assert sample("uptime_notifications_total", status="sent") - sent == 1

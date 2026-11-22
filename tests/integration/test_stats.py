"""Statistics with known data, so every number can be checked by hand."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CheckResult, Incident, Monitor, User
from app.services.stats import get_monitor_stats, uptime_by_monitor

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
BASE = "/api/v1/monitors"


def make_monitor(db: Session, email: str = "stats@example.com") -> Monitor:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, hashed_password="!")
        db.add(user)
        db.flush()
    monitor = Monitor(user_id=user.id, name="m", url="https://example.com/")
    db.add(monitor)
    db.flush()
    return monitor


def add_check(
    db: Session, monitor_id: int, minutes_ago: float, is_up: bool, ms: int | None
) -> None:
    db.add(
        CheckResult(
            monitor_id=monitor_id,
            checked_at=NOW - timedelta(minutes=minutes_ago),
            is_up=is_up,
            status_code=200 if is_up else None,
            response_time_ms=ms,
            error=None if is_up else "timeout",
        )
    )


@pytest.fixture
def known_monitor(db_session: Session) -> Monitor:
    """9 successful checks (100..900 ms), 1 failed check, 1 check older than 24h."""
    monitor = make_monitor(db_session)
    for i in range(1, 10):
        add_check(db_session, monitor.id, minutes_ago=i * 10, is_up=True, ms=i * 100)
    add_check(db_session, monitor.id, minutes_ago=5, is_up=False, ms=None)
    add_check(db_session, monitor.id, minutes_ago=25 * 60, is_up=False, ms=None)  # outside 24h
    # Resolved 10-minute incident inside the period.
    db_session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=NOW - timedelta(hours=3),
            resolved_at=NOW - timedelta(hours=3) + timedelta(minutes=10),
            cause="timeout",
        )
    )
    # Ongoing incident started 5 minutes ago.
    db_session.add(
        Incident(monitor_id=monitor.id, started_at=NOW - timedelta(minutes=5), cause="x")
    )
    db_session.flush()
    return monitor


def test_stats_with_known_data(db_session: Session, known_monitor: Monitor) -> None:
    stats = get_monitor_stats(db_session, known_monitor.id, "24h", now=NOW)

    assert stats.total_checks == 10
    assert stats.successful_checks == 9
    assert stats.uptime_percent == 90.0
    assert stats.avg_response_time_ms == 500.0  # (100 + ... + 900) / 9
    # percentile_cont: position (9 - 1) * 0.95 = 7.6 -> 800 + 0.6 * (900 - 800) = 860
    assert stats.p95_response_time_ms == 860.0
    assert stats.incident_count == 2
    assert stats.downtime_seconds == 10 * 60 + 5 * 60


def test_longer_period_includes_older_checks(db_session: Session, known_monitor: Monitor) -> None:
    stats = get_monitor_stats(db_session, known_monitor.id, "7d", now=NOW)

    assert stats.total_checks == 11
    assert stats.uptime_percent == pytest.approx(9 * 100 / 11, abs=0.001)


def test_incident_partly_before_period_counts_only_inside_part(db_session: Session) -> None:
    monitor = make_monitor(db_session)
    db_session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=NOW - timedelta(hours=25),  # 1 hour before the 24h window
            resolved_at=NOW - timedelta(hours=23),
            cause="timeout",
        )
    )
    db_session.flush()

    stats = get_monitor_stats(db_session, monitor.id, "24h", now=NOW)

    assert stats.incident_count == 1
    assert stats.downtime_seconds == 3600


def test_stats_without_data(db_session: Session) -> None:
    monitor = make_monitor(db_session)

    stats = get_monitor_stats(db_session, monitor.id, "24h", now=NOW)

    assert stats.total_checks == 0
    assert stats.uptime_percent is None
    assert stats.avg_response_time_ms is None
    assert stats.p95_response_time_ms is None
    assert stats.incident_count == 0
    assert stats.downtime_seconds == 0


def test_uptime_by_monitor_in_one_query(db_session: Session) -> None:
    a, b, empty = make_monitor(db_session), make_monitor(db_session), make_monitor(db_session)
    add_check(db_session, a.id, 1, True, 10)
    add_check(db_session, a.id, 2, False, None)
    add_check(db_session, b.id, 1, True, 10)
    db_session.flush()

    result = uptime_by_monitor(db_session, [a.id, b.id, empty.id], since=NOW - timedelta(hours=1))

    assert result == {a.id: 50.0, b.id: 100.0, empty.id: None}
    assert uptime_by_monitor(db_session, [], since=NOW) == {}


# ------------------------------------------------------------------ endpoints


@pytest.fixture
def owned_monitor_id(auth_client: TestClient) -> int:
    return auth_client.post(BASE, json={"name": "Site", "url": "https://example.com"}).json()["id"]


def test_stats_endpoint(auth_client: TestClient, owned_monitor_id: int) -> None:
    response = auth_client.get(f"{BASE}/{owned_monitor_id}/stats", params={"period": "7d"})

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "7d"
    assert body["total_checks"] == 0
    assert body["uptime_percent"] is None


def test_stats_endpoint_rejects_unknown_period(
    auth_client: TestClient, owned_monitor_id: int
) -> None:
    response = auth_client.get(f"{BASE}/{owned_monitor_id}/stats", params={"period": "1y"})

    assert response.status_code == 422


def test_checks_endpoint_filters_and_orders(
    auth_client: TestClient, owned_monitor_id: int, db_session: Session
) -> None:
    for minutes_ago in (30, 20, 10):
        add_check(db_session, owned_monitor_id, minutes_ago, True, minutes_ago)
    db_session.flush()

    newest_first = auth_client.get(f"{BASE}/{owned_monitor_id}/checks").json()
    filtered = auth_client.get(
        f"{BASE}/{owned_monitor_id}/checks",
        params={"from": (NOW - timedelta(minutes=25)).isoformat(), "limit": 1},
    ).json()

    assert [c["response_time_ms"] for c in newest_first] == [10, 20, 30]
    assert [c["response_time_ms"] for c in filtered] == [10]


def test_checks_limit_is_capped(auth_client: TestClient, owned_monitor_id: int) -> None:
    assert auth_client.get(f"{BASE}/{owned_monitor_id}/checks?limit=501").status_code == 422


def test_incidents_endpoint(
    auth_client: TestClient, owned_monitor_id: int, db_session: Session
) -> None:
    db_session.add(
        Incident(
            monitor_id=owned_monitor_id,
            started_at=NOW - timedelta(days=1),
            cause="old",
            resolved_at=NOW - timedelta(hours=23),
        )
    )
    db_session.add(Incident(monitor_id=owned_monitor_id, started_at=NOW, cause="new"))
    db_session.flush()

    incidents = auth_client.get(f"{BASE}/{owned_monitor_id}/incidents").json()

    assert [i["cause"] for i in incidents] == ["new", "old"]
    assert incidents[0]["resolved_at"] is None


def test_other_users_stats_return_404(
    client: TestClient,
    register_and_login: Callable[..., dict[str, str]],
) -> None:
    alice = register_and_login("alice@example.com")
    bob = register_and_login("bob@example.com")
    monitor_id = client.post(
        BASE, json={"name": "a", "url": "https://example.com"}, headers=alice
    ).json()["id"]

    for path in ("stats", "checks", "incidents"):
        assert client.get(f"{BASE}/{monitor_id}/{path}", headers=bob).status_code == 404

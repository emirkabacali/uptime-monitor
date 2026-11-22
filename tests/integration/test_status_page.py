from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import CheckResult, Incident, Monitor, MonitorStatus, User


def setup_page(db: Session) -> User:
    user = User(email="private.person@example.com", hashed_password="!", status_slug="acme")
    db.add(user)
    db.flush()
    now = datetime.now(UTC)
    public_up = Monitor(
        user_id=user.id,
        name="Public API",
        url="https://example.com/secret-path",
        is_public=True,
        status=MonitorStatus.UP,
    )
    public_down = Monitor(
        user_id=user.id,
        name="Public Website",
        url="https://example.org/",
        is_public=True,
        status=MonitorStatus.DOWN,
    )
    private = Monitor(
        user_id=user.id,
        name="Internal Admin Panel",
        url="https://example.com/admin",
        is_public=False,
        status=MonitorStatus.DOWN,
    )
    db.add_all([public_up, public_down, private])
    db.flush()
    for i, is_up in enumerate([True, True, True, False]):
        db.add(
            CheckResult(monitor_id=public_up.id, checked_at=now - timedelta(minutes=i), is_up=is_up)
        )
    db.add(
        Incident(monitor_id=public_down.id, started_at=now - timedelta(minutes=12), cause="timeout")
    )
    db.add(
        Incident(
            monitor_id=private.id, started_at=now - timedelta(minutes=3), cause="private-cause"
        )
    )
    db.flush()
    return user


def test_status_page_shows_public_monitors(client: TestClient, db_session: Session) -> None:
    setup_page(db_session)

    response = client.get("/status/acme")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Public API" in html
    assert "Public Website" in html
    assert "75.00% uptime (24h)" in html
    assert "Some systems are down" in html
    assert "timeout" in html
    assert 'http-equiv="refresh" content="60"' in html


def test_status_page_hides_private_data(client: TestClient, db_session: Session) -> None:
    setup_page(db_session)

    html = client.get("/status/acme").text

    assert "Internal Admin Panel" not in html  # private monitor
    assert "private-cause" not in html  # its incident
    assert "private.person@example.com" not in html  # owner's e-mail
    assert "secret-path" not in html  # monitored URLs are never shown


def test_all_operational_banner(client: TestClient, db_session: Session) -> None:
    user = User(email="ok@example.com", hashed_password="!", status_slug="all-good")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Monitor(
            user_id=user.id,
            name="API",
            url="https://example.com/",
            is_public=True,
            status=MonitorStatus.UP,
        )
    )
    db_session.flush()

    html = client.get("/status/all-good").text

    assert "All systems operational" in html
    assert "no data (24h)" in html


def test_status_page_without_public_monitors(client: TestClient, db_session: Session) -> None:
    db_session.add(User(email="empty@example.com", hashed_password="!", status_slug="empty"))
    db_session.flush()

    response = client.get("/status/empty")

    assert response.status_code == 200
    assert "No public monitors yet." in response.text


def test_unknown_slug_returns_404(client: TestClient) -> None:
    response = client.get("/status/does-not-exist")

    assert response.status_code == 404
    assert "Status page not found" in response.text

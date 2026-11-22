"""A user can only see and change their own monitors."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings

BASE = "/api/v1/monitors"
MONITOR = {"name": "Alice's site", "url": "https://example.com"}


@pytest.fixture
def two_users(
    register_and_login: Callable[..., dict[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    return register_and_login("alice@example.com"), register_and_login("bob@example.com")


def test_other_users_monitor_returns_404(client: TestClient, two_users) -> None:
    alice, bob = two_users
    monitor_id = client.post(BASE, json=MONITOR, headers=alice).json()["id"]

    assert client.get(f"{BASE}/{monitor_id}", headers=bob).status_code == 404
    assert client.patch(f"{BASE}/{monitor_id}", json={"name": "x"}, headers=bob).status_code == 404
    assert client.delete(f"{BASE}/{monitor_id}", headers=bob).status_code == 404
    assert client.post(f"{BASE}/{monitor_id}/pause", headers=bob).status_code == 404
    assert client.post(f"{BASE}/{monitor_id}/resume", headers=bob).status_code == 404
    # Alice's monitor is untouched.
    assert client.get(f"{BASE}/{monitor_id}", headers=alice).json()["name"] == "Alice's site"


def test_list_only_shows_own_monitors(client: TestClient, two_users) -> None:
    alice, bob = two_users
    client.post(BASE, json=MONITOR, headers=alice)

    bob_page = client.get(BASE, headers=bob).json()

    assert bob_page["total"] == 0
    assert bob_page["items"] == []


def test_monitor_limit_returns_409(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_monitors_per_user", 2)
    for i in range(2):
        assert auth_client.post(BASE, json=MONITOR | {"name": f"m{i}"}).status_code == 201

    response = auth_client.post(BASE, json=MONITOR)

    assert response.status_code == 409
    assert response.json()["code"] == "monitor_limit_reached"

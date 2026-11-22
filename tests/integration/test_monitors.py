from typing import Any

import pytest
from fastapi.testclient import TestClient

BASE = "/api/v1/monitors"


def create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = {"name": "Example", "url": "https://example.com"} | overrides
    response = client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_monitor_with_defaults(client: TestClient) -> None:
    monitor = create(client)

    assert monitor["id"] > 0
    assert monitor["name"] == "Example"
    assert monitor["url"] == "https://example.com/"
    assert monitor["interval_seconds"] == 60
    assert monitor["timeout_seconds"] == 10
    assert monitor["is_active"] is True
    assert monitor["is_public"] is False
    assert monitor["status"] == "UNKNOWN"
    assert monitor["consecutive_failures"] == 0
    assert monitor["last_checked_at"] is None


def test_get_monitor(client: TestClient) -> None:
    monitor = create(client)

    response = client.get(f"{BASE}/{monitor['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == monitor["id"]


def test_get_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.get(f"{BASE}/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found", "code": "not_found"}


def test_list_monitors_with_pagination(client: TestClient) -> None:
    for i in range(3):
        create(client, name=f"Site {i}")

    first_page = client.get(BASE, params={"limit": 2, "offset": 0}).json()
    second_page = client.get(BASE, params={"limit": 2, "offset": 2}).json()

    assert first_page["total"] == 3
    assert [m["name"] for m in first_page["items"]] == ["Site 0", "Site 1"]
    assert [m["name"] for m in second_page["items"]] == ["Site 2"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_rejects_invalid_pagination(client: TestClient, params: dict[str, int]) -> None:
    response = client.get(BASE, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_update_monitor(client: TestClient) -> None:
    monitor = create(client)

    response = client.patch(
        f"{BASE}/{monitor['id']}", json={"name": "Renamed", "interval_seconds": 120}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["interval_seconds"] == 120
    assert body["url"] == monitor["url"]


def test_update_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.patch(f"{BASE}/999999", json={"name": "x"})

    assert response.status_code == 404


def test_delete_monitor(client: TestClient) -> None:
    monitor = create(client)

    response = client.delete(f"{BASE}/{monitor['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"{BASE}/{monitor['id']}").status_code == 404


def test_delete_missing_monitor_returns_404(client: TestClient) -> None:
    assert client.delete(f"{BASE}/999999").status_code == 404


def test_pause_and_resume(client: TestClient) -> None:
    monitor = create(client)

    paused = client.post(f"{BASE}/{monitor['id']}/pause")
    resumed = client.post(f"{BASE}/{monitor['id']}/resume")

    assert paused.status_code == 200
    assert paused.json()["is_active"] is False
    assert resumed.status_code == 200
    assert resumed.json()["is_active"] is True


def test_pause_missing_monitor_returns_404(client: TestClient) -> None:
    assert client.post(f"{BASE}/999999/pause").status_code == 404
    assert client.post(f"{BASE}/999999/resume").status_code == 404

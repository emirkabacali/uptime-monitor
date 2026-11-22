from typing import Any

import pytest
from fastapi.testclient import TestClient

BASE = "/api/v1/monitors"
VALID = {"name": "Example", "url": "https://example.com"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval_seconds": 5},
        {"interval_seconds": 29},
        {"interval_seconds": 3601},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"name": ""},
        {"name": "x" * 101},
        {"url": "not a url"},
        {"url": "ftp://example.com"},
        {"url": "https://example.com/" + "a" * 2048},
    ],
)
def test_create_rejects_invalid_input(auth_client: TestClient, overrides: dict[str, Any]) -> None:
    response = auth_client.post(BASE, json=VALID | overrides)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("missing", ["name", "url"])
def test_create_requires_fields(auth_client: TestClient, missing: str) -> None:
    payload = {k: v for k, v in VALID.items() if k != missing}

    response = auth_client.post(BASE, json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval_seconds": 30},
        {"interval_seconds": 3600},
        {"timeout_seconds": 1},
        {"timeout_seconds": 30},
        {"name": "x" * 100},
    ],
)
def test_create_accepts_boundary_values(auth_client: TestClient, overrides: dict[str, Any]) -> None:
    response = auth_client.post(BASE, json=VALID | overrides)

    assert response.status_code == 201


def test_update_rejects_invalid_interval(auth_client: TestClient) -> None:
    monitor_id = auth_client.post(BASE, json=VALID).json()["id"]

    response = auth_client.patch(f"{BASE}/{monitor_id}", json={"interval_seconds": 5})

    assert response.status_code == 422


def test_changing_url_resets_state(auth_client: TestClient) -> None:
    monitor_id = auth_client.post(BASE, json=VALID).json()["id"]

    response = auth_client.patch(f"{BASE}/{monitor_id}", json={"url": "https://example.org"})

    assert response.status_code == 200
    assert response.json()["url"] == "https://example.org/"
    assert response.json()["status"] == "UNKNOWN"

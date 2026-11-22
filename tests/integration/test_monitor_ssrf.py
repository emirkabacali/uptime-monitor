"""Monitors pointing to internal addresses can never be created or saved."""

import pytest
from fastapi.testclient import TestClient

BASE = "/api/v1/monitors"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:5432/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://internal.example.com/",
    ],
)
def test_create_rejects_internal_targets(auth_client: TestClient, url: str) -> None:
    response = auth_client.post(BASE, json={"name": "evil", "url": url})

    assert response.status_code == 422
    assert response.json()["code"] == "ssrf_blocked"


def test_create_rejects_credentials_in_url(auth_client: TestClient) -> None:
    response = auth_client.post(BASE, json={"name": "x", "url": "http://user:pass@example.com/"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_url"


def test_create_rejects_unresolvable_host(auth_client: TestClient) -> None:
    response = auth_client.post(BASE, json={"name": "x", "url": "https://nope.invalid/"})

    assert response.status_code == 422
    assert response.json()["code"] == "dns_error"


def test_update_rejects_internal_target(auth_client: TestClient) -> None:
    monitor_id = auth_client.post(BASE, json={"name": "ok", "url": "https://example.com"}).json()[
        "id"
    ]

    response = auth_client.patch(f"{BASE}/{monitor_id}", json={"url": "http://127.0.0.1/"})

    assert response.status_code == 422
    assert auth_client.get(f"{BASE}/{monitor_id}").json()["url"] == "https://example.com/"

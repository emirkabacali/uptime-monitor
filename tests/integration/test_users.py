from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

ME = "/api/v1/users/me"


def test_read_me(auth_client: TestClient) -> None:
    response = auth_client.get(ME)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert body["telegram_chat_id"] is None
    assert body["status_slug"] is None


def test_update_me(auth_client: TestClient) -> None:
    response = auth_client.patch(ME, json={"telegram_chat_id": "123456789", "status_slug": "emir"})

    assert response.status_code == 200
    assert response.json()["telegram_chat_id"] == "123456789"
    assert response.json()["status_slug"] == "emir"


def test_update_me_partial_keeps_other_fields(auth_client: TestClient) -> None:
    auth_client.patch(ME, json={"telegram_chat_id": "42", "status_slug": "keep-me"})

    response = auth_client.patch(ME, json={"telegram_chat_id": "43"})

    assert response.json()["status_slug"] == "keep-me"


def test_update_me_null_clears_field(auth_client: TestClient) -> None:
    auth_client.patch(ME, json={"status_slug": "clear-me"})

    response = auth_client.patch(ME, json={"status_slug": None})

    assert response.json()["status_slug"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"status_slug": "Upper"},
        {"status_slug": "-starts-with-hyphen"},
        {"status_slug": "ab"},
        {"status_slug": "has space"},
        {"telegram_chat_id": "abc"},
    ],
)
def test_update_me_rejects_invalid_values(auth_client: TestClient, payload: dict) -> None:
    assert auth_client.patch(ME, json=payload).status_code == 422


def test_status_slug_must_be_unique(
    client: TestClient, register_and_login: Callable[..., dict[str, str]]
) -> None:
    alice = register_and_login("alice@example.com")
    bob = register_and_login("bob@example.com")
    client.patch(ME, json={"status_slug": "shared"}, headers=alice)

    response = client.patch(ME, json={"status_slug": "shared"}, headers=bob)

    assert response.status_code == 409
    assert response.json()["code"] == "slug_taken"

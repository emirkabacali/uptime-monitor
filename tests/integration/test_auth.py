from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models import User

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"
PASSWORD = "correct-horse-battery"


def test_register_creates_user(client: TestClient) -> None:
    response = client.post(REGISTER, json={"email": "Alice@Example.com", "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"  # stored lowercase
    assert "password" not in body
    assert "hashed_password" not in body


def test_password_is_stored_hashed(client: TestClient, db_session: Session) -> None:
    client.post(REGISTER, json={"email": "hash@example.com", "password": PASSWORD})

    user = db_session.scalar(select(User).where(User.email == "hash@example.com"))

    assert user is not None
    assert user.hashed_password != PASSWORD
    assert user.hashed_password.startswith("$argon2id$")


def test_register_duplicate_email_returns_409(client: TestClient) -> None:
    client.post(REGISTER, json={"email": "dup@example.com", "password": PASSWORD})

    response = client.post(REGISTER, json={"email": "DUP@example.com", "password": PASSWORD})

    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(REGISTER, json={"email": "short@example.com", "password": "1234567"})

    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(REGISTER, json={"email": "not-an-email", "password": PASSWORD})

    assert response.status_code == 422


def test_login_returns_bearer_token(client: TestClient) -> None:
    client.post(REGISTER, json={"email": "login@example.com", "password": PASSWORD})

    response = client.post(LOGIN, data={"username": "LOGIN@example.com", "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    token = response.json()["access_token"]
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    client.post(REGISTER, json={"email": "wrong@example.com", "password": PASSWORD})

    response = client.post(LOGIN, data={"username": "wrong@example.com", "password": "nope-nope"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_login_unknown_email_returns_401(client: TestClient) -> None:
    response = client.post(LOGIN, data={"username": "ghost@example.com", "password": PASSWORD})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_request_without_token_returns_401(client: TestClient) -> None:
    assert client.get(ME).status_code == 401
    assert client.get("/api/v1/monitors").status_code == 401
    assert client.post("/api/v1/monitors", json={}).status_code == 401


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get(ME, headers={"Authorization": "Bearer not.a.token"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_expired_token_returns_401(
    client: TestClient, register_and_login: Callable[..., dict[str, str]], db_session: Session
) -> None:
    register_and_login("expired@example.com")
    user_id = db_session.scalar(select(User.id).where(User.email == "expired@example.com"))
    assert user_id is not None
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_token_for_deleted_user_returns_401(client: TestClient) -> None:
    token = create_access_token(987654321)

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401

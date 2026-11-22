import time

import redis
from fastapi.testclient import TestClient

from app.core.redis import get_redis, make_redis
from app.main import app

LOGIN = "/api/v1/auth/login"


def broken_redis() -> redis.Redis:
    """The production client settings, pointing at a port where nothing listens."""
    return make_redis("redis://127.0.0.1:1/0")


def test_login_is_rate_limited_per_ip(client: TestClient) -> None:
    form = {"username": "someone@example.com", "password": "wrong-password"}
    statuses = [client.post(LOGIN, data=form).status_code for _ in range(10)]

    blocked = client.post(LOGIN, data=form)

    assert statuses == [401] * 10
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_requests"
    assert 0 < int(blocked.headers["Retry-After"]) <= 60


def test_rate_limiter_fails_open_when_redis_is_down(client: TestClient) -> None:
    app.dependency_overrides[get_redis] = broken_redis
    form = {"username": "someone@example.com", "password": "wrong-password"}

    started = time.perf_counter()
    statuses = {client.post(LOGIN, data=form).status_code for _ in range(12)}
    elapsed = time.perf_counter() - started

    assert statuses == {401}  # never 429, never 500
    assert elapsed < 5  # fails fast instead of retrying with backoff


def test_ready_when_dependencies_are_up(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


def test_not_ready_when_redis_is_down(client: TestClient) -> None:
    app.dependency_overrides[get_redis] = broken_redis

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}


def test_health_does_not_depend_on_redis(client: TestClient) -> None:
    app.dependency_overrides[get_redis] = broken_redis

    assert client.get("/health").status_code == 200

"""Shared pytest fixtures.

Database strategy: tests run against a real PostgreSQL database (same engine as
production, no SQLite). The schema is created once per test run with Alembic,
then every test runs inside a transaction that is rolled back at the end, so
tests never see each other's data.
"""

import os
from collections.abc import Callable, Iterator

# Test configuration must be in the environment before the app is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-signing")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

AuthHeaders = dict[str, str]
DEFAULT_PASSWORD = "correct-horse-battery"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5433/uptime_test"
)


def _create_database_if_missing(url: str) -> None:
    db_url = make_url(url)
    admin_engine = create_engine(db_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_url.database}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _create_database_if_missing(TEST_DATABASE_URL)
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    alembic_cfg.attributes["configure_logger"] = False
    command.upgrade(alembic_cfg, "head")

    test_engine = create_engine(TEST_DATABASE_URL)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose work is always rolled back after the test.

    `create_savepoint` turns the application's own `commit()` calls into
    savepoint releases, so the outer transaction can still be rolled back.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """An HTTP client that calls the app in-process, using the test session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def register_and_login(client: TestClient) -> Callable[..., AuthHeaders]:
    """Create a user and return the Authorization header for them."""

    def _register_and_login(email: str, password: str = DEFAULT_PASSWORD) -> AuthHeaders:
        response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert response.status_code == 201, response.text
        response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _register_and_login


@pytest.fixture
def auth_client(client: TestClient, register_and_login: Callable[..., AuthHeaders]) -> TestClient:
    """The same client, logged in as owner@example.com."""
    client.headers.update(register_and_login("owner@example.com"))
    return client

"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An HTTP client that calls the app in-process (no real server needed)."""
    with TestClient(app) as test_client:
        yield test_client

"""Fixed-window rate limiter, with a frozen clock so window boundaries are explicit."""

import pytest

from app.core import rate_limit
from app.core.redis import get_redis


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    now = {"t": 1_800_000_000.0}  # exactly the start of a minute
    monkeypatch.setattr(rate_limit.time, "time", lambda: now["t"])
    return now


def test_limit_within_one_window(clock: dict[str, float]) -> None:
    client = get_redis()
    results = [rate_limit.hit(client, "unit", limit=3) for _ in range(4)]

    assert results == [None, None, None, 60]


def test_new_window_resets_the_counter(clock: dict[str, float]) -> None:
    client = get_redis()
    for _ in range(3):
        rate_limit.hit(client, "unit", limit=3)

    clock["t"] += 60  # next minute

    assert rate_limit.hit(client, "unit", limit=3) is None


def test_burst_at_window_boundary_is_a_known_tradeoff(clock: dict[str, float]) -> None:
    """Fixed windows allow up to 2x the limit around a boundary (documented trade-off)."""
    client = get_redis()
    clock["t"] += 59
    end_of_window = [rate_limit.hit(client, "unit", limit=3) for _ in range(3)]
    clock["t"] += 1
    start_of_next = [rate_limit.hit(client, "unit", limit=3) for _ in range(3)]

    assert end_of_window == start_of_next == [None, None, None]

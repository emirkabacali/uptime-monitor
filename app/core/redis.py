"""Shared Redis client (also the Celery broker)."""

from functools import lru_cache

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import get_settings


def make_redis(url: str) -> redis.Redis:
    """Create a client that fails fast.

    redis-py retries failed commands with backoff by default, which made every
    login take seconds while Redis was down. The API only uses Redis for rate
    limiting and readiness checks, so one quick retry is enough.
    """
    return redis.Redis.from_url(
        url,
        socket_timeout=1,
        socket_connect_timeout=1,
        retry=Retry(NoBackoff(), retries=1),
    )


@lru_cache
def get_redis() -> redis.Redis:
    return make_redis(get_settings().redis_url)

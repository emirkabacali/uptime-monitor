"""Fixed-window rate limiting with Redis.

For each key and minute we keep a counter: INCR it, and give it an expiry the
first time. When the counter passes the limit, the request is rejected.
"""

import logging
import time

import redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


def hit(client: redis.Redis, key: str, limit: int, window: int = WINDOW_SECONDS) -> int | None:
    """Count one attempt. Return seconds to wait if the limit is exceeded, else None.

    If Redis is unavailable the request is allowed ("fail open"): a broken rate
    limiter must not lock every user out of the login endpoint.
    """
    now = int(time.time())
    window_start = now - now % window
    bucket = f"ratelimit:{key}:{window_start}"
    try:
        pipe = client.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window, nx=True)
        count, _ = pipe.execute()
    except redis.RedisError:
        logger.warning("Rate limiter unavailable, allowing request", extra={"key": key})
        return None
    if int(count) > limit:
        return window_start + window - now
    return None

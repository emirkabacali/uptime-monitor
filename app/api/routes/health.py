"""Health check endpoints.

- /health (liveness): is the process alive? Never touches dependencies, so a
  database outage does not make an orchestrator restart healthy API processes.
- /ready (readiness): can this instance serve traffic right now (DB + Redis)?
"""

import logging
from typing import Annotated

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: returns 200 as long as the process is running."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DbSession, client: Annotated[redis.Redis, Depends(get_redis)]) -> JSONResponse:
    """Readiness probe: 200 if PostgreSQL and Redis respond, otherwise 503."""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness check failed: database")
        checks["database"] = "error"
    try:
        client.ping()
        checks["redis"] = "ok"
    except redis.RedisError:
        logger.exception("Readiness check failed: redis")
        checks["redis"] = "error"

    is_ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )

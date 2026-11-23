"""FastAPI application entry point."""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import auth, health, monitors, status_page, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware

API_PREFIX = "/api/v1"

# Fail fast: invalid configuration (e.g. a short JWT_SECRET) stops startup here.
get_settings()
configure_logging()

app = FastAPI(
    title="Uptime Monitor",
    version="0.1.0",
    description="Monitors websites and APIs, records results and alerts on downtime.",
)

register_error_handlers(app)
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(monitors.router, prefix=API_PREFIX)
app.include_router(status_page.router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape endpoint. Internal only: Caddy does not serve it."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

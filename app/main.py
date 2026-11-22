"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import auth, health, monitors, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers

API_PREFIX = "/api/v1"

# Fail fast: invalid configuration (e.g. a short JWT_SECRET) stops startup here.
get_settings()

app = FastAPI(
    title="Uptime Monitor",
    version="0.1.0",
    description="Monitors websites and APIs, records results and alerts on downtime.",
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(monitors.router, prefix=API_PREFIX)

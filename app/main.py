"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import health, monitors
from app.core.errors import register_error_handlers

API_PREFIX = "/api/v1"

app = FastAPI(
    title="Uptime Monitor",
    version="0.1.0",
    description="Monitors websites and APIs, records results and alerts on downtime.",
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(monitors.router, prefix=API_PREFIX)

"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import health

app = FastAPI(
    title="Uptime Monitor",
    version="0.1.0",
    description="Monitors websites and APIs, records results and alerts on downtime.",
)

app.include_router(health.router)

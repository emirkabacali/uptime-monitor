"""Response models for check history, statistics and incidents."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    checked_at: datetime
    is_up: bool
    status_code: int | None
    response_time_ms: int | None
    error: str | None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    resolved_at: datetime | None
    cause: str


class MonitorStatsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period: str
    start: datetime
    end: datetime
    total_checks: int
    successful_checks: int
    uptime_percent: float | None
    avg_response_time_ms: float | None
    p95_response_time_ms: float | None
    incident_count: int
    downtime_seconds: int

"""Request and response models for monitors."""

from datetime import datetime
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints

from app.models.monitor import MonitorStatus

# Only http/https, max 2048 characters (same as the database column).
HttpUrl = Annotated[AnyHttpUrl, UrlConstraints(max_length=2048, allowed_schemes=["http", "https"])]
Name = Annotated[str, Field(min_length=1, max_length=100)]
IntervalSeconds = Annotated[int, Field(ge=30, le=3600)]
TimeoutSeconds = Annotated[int, Field(ge=1, le=30)]


class MonitorCreate(BaseModel):
    name: Name
    url: HttpUrl
    interval_seconds: IntervalSeconds = 60
    timeout_seconds: TimeoutSeconds = 10
    is_public: bool = False


class MonitorUpdate(BaseModel):
    """All fields optional: only the fields sent are changed (PATCH)."""

    name: Name | None = None
    url: HttpUrl | None = None
    interval_seconds: IntervalSeconds | None = None
    timeout_seconds: TimeoutSeconds | None = None
    is_public: bool | None = None


class MonitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    interval_seconds: int
    timeout_seconds: int
    is_active: bool
    is_public: bool
    status: MonitorStatus
    consecutive_failures: int
    last_checked_at: datetime | None
    next_check_at: datetime
    created_at: datetime
    updated_at: datetime


class MonitorPage(BaseModel):
    items: list[MonitorRead]
    total: int
    limit: int
    offset: int

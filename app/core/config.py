"""Application settings loaded from environment variables (12-factor style)."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    """All configuration comes from the environment or a local `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str = "postgresql+psycopg://app:app@localhost:5433/uptime"
    redis_url: str = "redis://localhost:6379/0"
    # Connections per process. Keep (pool + overflow) x processes below
    # PostgreSQL's max_connections (100 by default).
    db_pool_size: int = Field(default=20, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # Required, no default: the application refuses to start without a strong secret.
    jwt_secret: SecretStr
    jwt_expire_minutes: int = Field(default=60, ge=1)

    max_monitors_per_user: int = Field(default=20, ge=1)

    # Monitor state machine: failed checks in a row before a monitor is DOWN.
    failure_threshold: int = Field(default=3, ge=1)

    # Scheduler and retention.
    dispatch_batch_size: int = Field(default=500, ge=1)
    check_retention_days: int = Field(default=30, ge=1)

    # Telegram notifications are disabled when the token is empty.
    telegram_bot_token: SecretStr | None = None

    # Login attempts allowed per client IP per minute.
    login_rate_limit_per_minute: int = Field(default=10, ge=1)

    # SSRF protection switch. Only for tests against local servers; never in production.
    allow_private_targets: bool = False

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_long(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return value

    @model_validator(mode="after")
    def no_private_targets_in_production(self) -> Self:
        if self.environment == "production" and self.allow_private_targets:
            raise ValueError("ALLOW_PRIVATE_TARGETS must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read the environment only once)."""
    return Settings()

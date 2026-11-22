"""Application settings loaded from environment variables (12-factor style)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    """All configuration comes from the environment or a local `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str = "postgresql+psycopg://app:app@localhost:5433/uptime"

    # Required, no default: the application refuses to start without a strong secret.
    jwt_secret: SecretStr
    jwt_expire_minutes: int = Field(default=60, ge=1)

    max_monitors_per_user: int = Field(default=20, ge=1)

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_long(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read the environment only once)."""
    return Settings()

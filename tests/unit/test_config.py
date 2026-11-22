import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG_SECRET = "a" * 32


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = Settings(_env_file=None, jwt_secret=STRONG_SECRET)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.jwt_expire_minutes == 60
    assert settings.max_monitors_per_user == 20


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    settings = Settings(_env_file=None, jwt_secret=STRONG_SECRET)

    assert settings.environment == "production"
    assert settings.log_level == "WARNING"


def test_rejects_invalid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=STRONG_SECRET)


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None, jwt_secret="a" * 31)


def test_secret_is_hidden_in_repr() -> None:
    settings = Settings(_env_file=None, jwt_secret=STRONG_SECRET)

    assert STRONG_SECRET not in repr(settings)

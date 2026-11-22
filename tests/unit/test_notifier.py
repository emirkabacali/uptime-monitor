import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import get_settings
from app.services.notifier import (
    NotificationError,
    TelegramNotifier,
    format_down_message,
    format_duration,
    format_recovered_message,
    get_notifier,
)

TOKEN = "123456:TEST-TOKEN"
SEND_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


@respx.mock
def test_telegram_send_posts_message() -> None:
    route = respx.post(SEND_URL).respond(200, json={"ok": True})

    TelegramNotifier(TOKEN).send("42", "hello")

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"chat_id": "42", "text": "hello", "disable_web_page_preview": True}


@respx.mock
def test_telegram_long_message_is_truncated() -> None:
    route = respx.post(SEND_URL).respond(200, json={"ok": True})

    TelegramNotifier(TOKEN).send("42", "x" * 5000)

    assert len(json.loads(route.calls.last.request.content)["text"]) == 4096


@respx.mock
def test_telegram_error_status_raises() -> None:
    respx.post(SEND_URL).respond(400, json={"ok": False, "description": "chat not found"})

    with pytest.raises(NotificationError, match="400: chat not found"):
        TelegramNotifier(TOKEN).send("42", "hello")


@respx.mock
def test_telegram_network_error_raises_without_leaking_token() -> None:
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(NotificationError) as exc_info:
        TelegramNotifier(TOKEN).send("42", "hello")

    assert TOKEN not in str(exc_info.value)


@respx.mock
def test_telegram_uses_given_client() -> None:
    respx.post(SEND_URL).respond(200, json={"ok": True})

    with httpx.Client() as client:
        TelegramNotifier(TOKEN, client=client).send("42", "hello")


def test_get_notifier_is_none_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", None)

    assert get_notifier() is None


def test_get_notifier_returns_telegram_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "telegram_bot_token", SecretStr(TOKEN))

    assert isinstance(get_notifier(), TelegramNotifier)


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=45), "45s"),
        (timedelta(minutes=12, seconds=30), "12m"),
        (timedelta(hours=1), "1h"),
        (timedelta(hours=1, minutes=5), "1h 5m"),
        (timedelta(days=2), "2d"),
        (timedelta(days=2, hours=3, minutes=10), "2d 3h"),
        (timedelta(seconds=-5), "0s"),
    ],
)
def test_format_duration(delta: timedelta, expected: str) -> None:
    assert format_duration(delta) == expected


def test_down_message() -> None:
    since = datetime(2026, 11, 23, 21, 1, tzinfo=UTC)

    text = format_down_message("My Site", "https://example.com/", "timeout", since)

    assert text == "🔴 DOWN: My Site (https://example.com/) — timeout\nSince: 2026-11-23 21:01 UTC"


def test_recovered_message() -> None:
    text = format_recovered_message("My Site", "https://example.com/", timedelta(minutes=12))

    assert text == "🟢 RECOVERED: My Site (https://example.com/) — downtime 12m"

"""Notifications behind a small interface.

`Notifier` is a Protocol: any class with a matching `send()` method is a
notifier. The worker only depends on this interface, so adding e-mail or Slack
later means writing one new class, without changing the check logic.
"""

import contextlib
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from app.core.config import get_settings

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096  # Telegram limit


class NotificationError(Exception):
    """Sending failed; the caller may retry."""


class Notifier(Protocol):
    def send(self, chat_id: str, text: str) -> None: ...


class TelegramNotifier:
    """Sends messages with the Telegram Bot API `sendMessage` method."""

    def __init__(
        self, token: str, *, client: httpx.Client | None = None, base_url: str = TELEGRAM_API
    ) -> None:
        self._token = token
        self._client = client
        self._base_url = base_url

    def send(self, chat_id: str, text: str) -> None:
        url = f"{self._base_url}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE_LENGTH],
            "disable_web_page_preview": True,
        }
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload, timeout=10)
            else:
                response = httpx.post(url, json=payload, timeout=10)
        except httpx.HTTPError as exc:
            # Never include the URL in the message: it contains the bot token.
            raise NotificationError(f"Telegram request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            description = ""
            with contextlib.suppress(ValueError):
                description = response.json().get("description", "")
            raise NotificationError(f"Telegram returned {response.status_code}: {description}")


def get_notifier() -> Notifier | None:
    """The configured notifier, or None when TELEGRAM_BOT_TOKEN is empty."""
    token = get_settings().telegram_bot_token
    if token is None or not token.get_secret_value():
        return None
    return TelegramNotifier(token.get_secret_value())


# ---------------------------------------------------------------- messages


def format_duration(duration: timedelta) -> str:
    """Human-friendly duration: 45s, 12m, 1h 5m, 2d 3h."""
    seconds = max(int(duration.total_seconds()), 0)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def format_down_message(name: str, url: str, error: str, since: datetime) -> str:
    return f"🔴 DOWN: {name} ({url}) — {error}\nSince: {since:%Y-%m-%d %H:%M} UTC"


def format_recovered_message(name: str, url: str, downtime: timedelta) -> str:
    return f"🟢 RECOVERED: {name} ({url}) — downtime {format_duration(downtime)}"


def format_test_message() -> str:
    return "✅ Test notification from Uptime Monitor. Alerts will arrive in this chat."

"""Logging setup shared by the API and the worker."""

import logging

from app.core.config import get_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO. The Telegram URL contains the bot
    # token, so these logs must never be emitted.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

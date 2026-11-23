"""Structured (JSON) logging shared by the API and the worker.

Every log line is one JSON object, so log tools can filter by field instead of
parsing text. The current `request_id` (API) or `task_id` (worker) is added to
every line automatically, which lets you follow one request from start to end.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)

# Attributes every LogRecord has; anything else was passed with `extra=` and is
# included in the JSON output.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

# Never write these to logs, even if someone passes them in `extra`.
SENSITIVE_KEYS = {"password", "token", "access_token", "authorization", "jwt", "secret"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if (request_id := request_id_var.get()) is not None:
            entry["request_id"] = request_id
        if (task_id := task_id_var.get()) is not None:
            entry["task_id"] = task_id
        for key, value in vars(record).items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            entry[key] = "[REDACTED]" if key.lower() in SENSITIVE_KEYS else value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level)

    # httpx logs every request URL at INFO. The Telegram URL contains the bot
    # token, so these logs must never be emitted.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Our middleware writes one structured line per request instead.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error", "celery"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

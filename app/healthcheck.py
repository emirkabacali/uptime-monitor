"""Container health checks (used by Docker HEALTHCHECK and docker compose).

    python -m app.healthcheck api      # GET /health on the local API
    python -m app.healthcheck worker   # the Celery worker answers a ping
    python -m app.healthcheck beat     # the beat schedule file was saved recently

Only the standard library and the app itself are used: the slim image has no
curl, and the check must stay fast and cheap.
"""

import os
import socket
import sys
import time
import urllib.request

BEAT_SCHEDULE_FILE = os.environ.get("BEAT_SCHEDULE_FILE", "/tmp/celerybeat-schedule")
# Beat saves its schedule file about every 3 minutes.
BEAT_MAX_AGE_SECONDS = 5 * 60


def check_api() -> bool:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
        return response.status == 200


def check_worker() -> bool:
    from app.worker.celery_app import celery_app

    replies = celery_app.control.ping(destination=[f"celery@{socket.gethostname()}"], timeout=3)
    return bool(replies)


def check_beat() -> bool:
    directory = os.path.dirname(BEAT_SCHEDULE_FILE) or "."
    prefix = os.path.basename(BEAT_SCHEDULE_FILE)
    mtimes = [
        os.path.getmtime(os.path.join(directory, name))
        for name in os.listdir(directory)
        if name.startswith(prefix)
    ]
    return bool(mtimes) and time.time() - max(mtimes) < BEAT_MAX_AGE_SECONDS


CHECKS = {"api": check_api, "worker": check_worker, "beat": check_beat}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in CHECKS:
        print(f"usage: python -m app.healthcheck [{'|'.join(CHECKS)}]", file=sys.stderr)
        return 2
    try:
        return 0 if CHECKS[argv[1]]() else 1
    except Exception as exc:  # any failure means unhealthy
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

import os
import time
from pathlib import Path

import pytest

from app import healthcheck


def test_unknown_role_prints_usage() -> None:
    assert healthcheck.main(["healthcheck"]) == 2
    assert healthcheck.main(["healthcheck", "nope"]) == 2


def test_beat_is_healthy_with_fresh_schedule_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule = tmp_path / "celerybeat-schedule"
    schedule.write_text("x")
    monkeypatch.setattr(healthcheck, "BEAT_SCHEDULE_FILE", str(schedule))

    assert healthcheck.main(["healthcheck", "beat"]) == 0


def test_beat_is_unhealthy_with_stale_or_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule = tmp_path / "celerybeat-schedule"
    monkeypatch.setattr(healthcheck, "BEAT_SCHEDULE_FILE", str(schedule))
    assert healthcheck.main(["healthcheck", "beat"]) == 1  # missing

    schedule.write_text("x")
    old = time.time() - 10 * 60
    os.utime(schedule, (old, old))
    assert healthcheck.main(["healthcheck", "beat"]) == 1  # stale


def test_exceptions_mean_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> bool:
        raise ConnectionError("refused")

    monkeypatch.setitem(healthcheck.CHECKS, "api", boom)

    assert healthcheck.main(["healthcheck", "api"]) == 1

"""Statistics computed in SQL (aggregation happens in PostgreSQL, not in Python).

- uptime % = successful checks / all checks * 100 (None when there are no checks)
- average and p95 response time, over SUCCESSFUL checks only: failed checks have
  no response time (timeouts, DNS errors) or measure an error page, which would
  distort the "how fast is the site" number
- incidents that overlap the period, and total downtime inside the period
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CheckResult, Incident

Period = Literal["24h", "7d", "30d"]
PERIODS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@dataclass(frozen=True)
class MonitorStats:
    period: str
    start: datetime
    end: datetime
    total_checks: int
    successful_checks: int
    uptime_percent: float | None
    avg_response_time_ms: float | None
    p95_response_time_ms: float | None
    incident_count: int
    downtime_seconds: int


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def get_monitor_stats(
    db: Session, monitor_id: int, period: Period, now: datetime | None = None
) -> MonitorStats:
    end = now or datetime.now(UTC)
    start = end - PERIODS[period]

    in_period = (
        CheckResult.monitor_id == monitor_id,
        CheckResult.checked_at >= start,
        CheckResult.checked_at <= end,
    )
    total, successful = db.execute(
        select(func.count(), func.count().filter(CheckResult.is_up)).where(*in_period)
    ).one()
    avg_ms, p95_ms = db.execute(
        select(
            func.avg(CheckResult.response_time_ms),
            # percentile_cont interpolates between neighbours, like most monitoring tools
            func.percentile_cont(0.95).within_group(CheckResult.response_time_ms),
        ).where(*in_period, CheckResult.is_up.is_(True))
    ).one()

    # An incident counts if it overlaps [start, end]. Downtime is only the part
    # inside the period; an open incident lasts until `end`.
    overlaps = (
        Incident.monitor_id == monitor_id,
        Incident.started_at < end,
        func.coalesce(Incident.resolved_at, end) > start,
    )
    clipped = func.least(func.coalesce(Incident.resolved_at, end), end) - func.greatest(
        Incident.started_at, start
    )
    incident_count, downtime = db.execute(
        select(func.count(), func.coalesce(func.sum(func.extract("epoch", clipped)), 0)).where(
            *overlaps
        )
    ).one()

    return MonitorStats(
        period=period,
        start=start,
        end=end,
        total_checks=total,
        successful_checks=successful,
        uptime_percent=_round(successful * 100 / total, 3) if total else None,
        avg_response_time_ms=_round(avg_ms),
        p95_response_time_ms=_round(p95_ms),
        incident_count=incident_count,
        downtime_seconds=int(downtime),
    )


def uptime_by_monitor(
    db: Session, monitor_ids: list[int], since: datetime
) -> dict[int, float | None]:
    """Uptime % per monitor in ONE grouped query (avoids an N+1 query loop)."""
    if not monitor_ids:
        return {}
    rows = db.execute(
        select(
            CheckResult.monitor_id,
            func.count(),
            func.count().filter(CheckResult.is_up),
        )
        .where(CheckResult.monitor_id.in_(monitor_ids), CheckResult.checked_at >= since)
        .group_by(CheckResult.monitor_id)
    ).all()
    result: dict[int, float | None] = dict.fromkeys(monitor_ids)
    for monitor_id, total, successful in rows:
        result[monitor_id] = round(successful * 100 / total, 2) if total else None
    return result

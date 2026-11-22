"""Public status page: server-side rendered HTML, no login required.

Privacy: only monitors marked `is_public` are shown, and only their names,
states and uptime. The owner's e-mail and the monitored URLs are never rendered.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import Incident, Monitor, MonitorStatus, User
from app.services.notifier import format_duration
from app.services.stats import uptime_by_monitor

router = APIRouter(tags=["status page"])

templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")
templates.env.filters["duration"] = format_duration

RECENT_INCIDENT_DAYS = 7
MAX_RECENT_INCIDENTS = 10


@router.get("/status/{slug}", response_class=HTMLResponse, include_in_schema=True)
def status_page(slug: str, request: Request, db: DbSession) -> HTMLResponse:
    user = db.scalar(select(User).where(User.status_slug == slug.lower()))
    if user is None:
        return templates.TemplateResponse(
            request, "status_not_found.html", {"slug": slug}, status_code=404
        )

    now = datetime.now(UTC)
    monitors = list(
        db.scalars(
            select(Monitor)
            .where(Monitor.user_id == user.id, Monitor.is_public.is_(True))
            .order_by(Monitor.name)
        )
    )
    ids = [m.id for m in monitors]
    uptime = uptime_by_monitor(db, ids, since=now - timedelta(hours=24))
    names = {m.id: m.name for m in monitors}
    incidents = (
        list(
            db.scalars(
                select(Incident)
                .where(
                    Incident.monitor_id.in_(ids),
                    Incident.started_at >= now - timedelta(days=RECENT_INCIDENT_DAYS),
                )
                .order_by(Incident.started_at.desc())
                .limit(MAX_RECENT_INCIDENTS)
            )
        )
        if ids
        else []
    )

    rows = [
        {
            "name": m.name,
            "state": "paused" if not m.is_active else m.status.value.lower(),
            "uptime": uptime[m.id],
        }
        for m in monitors
    ]
    any_down = any(m.is_active and m.status is MonitorStatus.DOWN for m in monitors)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "slug": user.status_slug,
            "monitors": rows,
            "any_down": any_down,
            "incidents": [
                {
                    "monitor": names[i.monitor_id],
                    "started_at": i.started_at,
                    "resolved_at": i.resolved_at,
                    "duration": (i.resolved_at or now) - i.started_at,
                    "cause": i.cause,
                }
                for i in incidents
            ],
            "generated_at": now,
        },
    )

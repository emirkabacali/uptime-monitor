"""Monitor CRUD endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.models import Monitor, MonitorStatus, User
from app.schemas.monitor import MonitorCreate, MonitorPage, MonitorRead, MonitorUpdate
from app.services.url_validator import URLValidationError, validate_target_url

router = APIRouter(prefix="/monitors", tags=["monitors"])


def ensure_safe_url(url: str) -> str:
    """Apply the SSRF rules to a user-supplied URL; invalid targets give 422."""
    try:
        validate_target_url(url)
    except URLValidationError as exc:
        raise AppError(422, str(exc), exc.code) from exc
    return url


def get_owned_monitor(db: DbSession, user: User, monitor_id: int) -> Monitor:
    """Load a monitor that belongs to the user, or raise 404.

    Another user's monitor also returns 404 (not 403) so we do not reveal
    that the id exists.
    """
    monitor = db.scalar(select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id))
    if monitor is None:
        raise NotFoundError("Monitor not found")
    return monitor


@router.post("", response_model=MonitorRead, status_code=status.HTTP_201_CREATED)
def create_monitor(payload: MonitorCreate, db: DbSession, user: CurrentUser) -> Monitor:
    limit = get_settings().max_monitors_per_user
    count = db.scalar(select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id))
    if (count or 0) >= limit:
        # 409 Conflict: the request is valid, but conflicts with the account's
        # current state (see docs/decisions/0001-monitor-limit-response.md).
        raise AppError(409, f"Monitor limit reached ({limit})", "monitor_limit_reached")
    url = ensure_safe_url(str(payload.url))
    monitor = Monitor(
        user_id=user.id,
        name=payload.name,
        url=url,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        is_public=payload.is_public,
        next_check_at=func.now(),
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


@router.get("", response_model=MonitorPage)
def list_monitors(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MonitorPage:
    owned = Monitor.user_id == user.id
    total = db.scalar(select(func.count()).select_from(Monitor).where(owned)) or 0
    items = db.scalars(
        select(Monitor).where(owned).order_by(Monitor.id).limit(limit).offset(offset)
    ).all()
    return MonitorPage(
        items=[MonitorRead.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{monitor_id}", response_model=MonitorRead)
def get_monitor(monitor_id: int, db: DbSession, user: CurrentUser) -> Monitor:
    return get_owned_monitor(db, user, monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorRead)
def update_monitor(
    monitor_id: int, payload: MonitorUpdate, db: DbSession, user: CurrentUser
) -> Monitor:
    monitor = get_owned_monitor(db, user, monitor_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "url" in changes:
        new_url = ensure_safe_url(str(changes.pop("url")))
        if new_url != monitor.url:
            # A different URL is a different target: start its history fresh.
            monitor.url = new_url
            monitor.status = MonitorStatus.UNKNOWN
            monitor.consecutive_failures = 0
            monitor.next_check_at = func.now()
    for field, value in changes.items():
        setattr(monitor, field, value)
    db.commit()
    db.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(monitor_id: int, db: DbSession, user: CurrentUser) -> Response:
    monitor = get_owned_monitor(db, user, monitor_id)
    db.delete(monitor)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/pause", response_model=MonitorRead)
def pause_monitor(monitor_id: int, db: DbSession, user: CurrentUser) -> Monitor:
    monitor = get_owned_monitor(db, user, monitor_id)
    monitor.is_active = False
    db.commit()
    db.refresh(monitor)
    return monitor


@router.post("/{monitor_id}/resume", response_model=MonitorRead)
def resume_monitor(monitor_id: int, db: DbSession, user: CurrentUser) -> Monitor:
    monitor = get_owned_monitor(db, user, monitor_id)
    if not monitor.is_active:
        monitor.is_active = True
        monitor.next_check_at = func.now()  # check soon after resuming
    db.commit()
    db.refresh(monitor)
    return monitor

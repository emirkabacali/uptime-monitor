"""Endpoints for the logged-in user's own profile."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AppError
from app.models import User
from app.schemas.user import UserRead, UserUpdate
from app.services.notifier import NotificationError, Notifier, format_test_message, get_notifier

router = APIRouter(prefix="/users", tags=["users"])


def _slug_taken() -> AppError:
    return AppError(409, "Status page slug is already taken", "slug_taken")


@router.get("/me", response_model=UserRead)
def read_me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserRead)
def update_me(payload: UserUpdate, db: DbSession, user: CurrentUser) -> User:
    changes = payload.model_dump(exclude_unset=True)
    slug = changes.get("status_slug")
    if slug is not None and slug != user.status_slug:
        taken = db.scalar(select(User.id).where(User.status_slug == slug, User.id != user.id))
        if taken is not None:
            raise _slug_taken()
    for field, value in changes.items():
        setattr(user, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _slug_taken() from exc
    db.refresh(user)
    return user


@router.post("/me/test-notification")
def send_test_notification(
    user: CurrentUser, notifier: Annotated[Notifier | None, Depends(get_notifier)]
) -> dict[str, str]:
    """Send a test message to your Telegram chat (synchronously, for instant feedback)."""
    if notifier is None:
        raise AppError(
            503, "Notifications are not configured on this server", "notifications_disabled"
        )
    if not user.telegram_chat_id:
        raise AppError(
            400,
            "Set telegram_chat_id with PATCH /api/v1/users/me first",
            "telegram_chat_id_missing",
        )
    try:
        notifier.send(user.telegram_chat_id, format_test_message())
    except NotificationError as exc:
        raise AppError(502, str(exc), "notification_failed") from exc
    return {"status": "sent"}

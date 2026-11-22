"""Endpoints for the logged-in user's own profile."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AppError
from app.models import User
from app.schemas.user import UserRead, UserUpdate

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

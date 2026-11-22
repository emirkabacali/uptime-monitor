"""Registration and login."""

from typing import Annotated

import redis
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.user import Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def limit_login_attempts(
    request: Request, client: Annotated[redis.Redis, Depends(get_redis)]
) -> None:
    """Allow LOGIN_RATE_LIMIT_PER_MINUTE attempts per client IP per minute."""
    ip = request.client.host if request.client else "unknown"
    retry_after = rate_limit.hit(client, f"login:{ip}", get_settings().login_rate_limit_per_minute)
    if retry_after is not None:
        raise AppError(
            429,
            "Too many login attempts. Try again later.",
            "too_many_requests",
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DbSession) -> User:
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise AppError(409, "Email is already registered", "email_taken")
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # two registrations with the same email at once
        db.rollback()
        raise AppError(409, "Email is already registered", "email_taken") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=Token, dependencies=[Depends(limit_login_attempts)])
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """OAuth2 password flow: send `username` (your email) and `password` as a form."""
    user = db.scalar(select(User).where(User.email == form.username.strip().lower()))
    if not verify_password(form.password, user.hashed_password if user else None):
        raise AppError(401, "Incorrect email or password", "invalid_credentials")
    assert user is not None
    return Token(access_token=create_access_token(user.id))

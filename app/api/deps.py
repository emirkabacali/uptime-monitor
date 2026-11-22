"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

# TEMPORARY (Phase 2): there is no authentication yet, so every request acts as
# one fixed seeded user. Phase 3 replaces this with the JWT-authenticated user.
SEED_USER_EMAIL = "seed@example.com"


def get_current_user(db: DbSession) -> User:
    user = db.scalar(select(User).where(User.email == SEED_USER_EMAIL))
    if user is None:
        # "!" can never match a password hash, so nobody can log in as this user.
        user = User(email=SEED_USER_EMAIL, hashed_password="!")
        db.add(user)
        db.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

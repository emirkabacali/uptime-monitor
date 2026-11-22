"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

# Tells Swagger where to log in; reads "Authorization: Bearer <token>".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class UnauthorizedError(AppError):
    def __init__(self, detail: str = "Could not validate credentials") -> None:
        super().__init__(401, detail, "unauthorized")


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    try:
        user_id = decode_token(token)
    except InvalidTokenError as exc:
        raise UnauthorizedError() from exc
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

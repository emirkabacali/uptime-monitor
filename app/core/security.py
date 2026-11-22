"""Password hashing (Argon2 via pwdlib) and JWT access tokens (PyJWT)."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"

# Argon2id with the library's recommended parameters. Each hash gets its own
# random salt, which is stored inside the hash string.
password_hash = PasswordHash.recommended()

# Used to spend the same time verifying a password when the user does not
# exist, so response timing does not reveal which emails are registered.
_DUMMY_HASH = password_hash.hash("dummy-password-for-timing")


class InvalidTokenError(Exception):
    """The token is malformed, has a bad signature or has expired."""


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if hashed is None:
        password_hash.verify(password, _DUMMY_HASH)
        return False
    try:
        return password_hash.verify(password, hashed)
    except PwdlibError:
        # Not a valid hash (e.g. a disabled account): never matches.
        return False


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = {"sub": str(user_id), "iat": now, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """Return the user id stored in a valid access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],  # never accept "none" or other algorithms
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise InvalidTokenError("not an access token")
    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("invalid subject") from exc

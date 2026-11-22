"""Request and response models for users and authentication."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

Email = Annotated[EmailStr, Field(max_length=255), AfterValidator(str.lower)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
# Lowercase letters, digits and hyphens; cannot start or end with a hyphen.
StatusSlug = Annotated[
    str, Field(min_length=3, max_length=50, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])$")
]
# Telegram chat ids are integers (negative for groups).
TelegramChatId = Annotated[str, Field(max_length=64, pattern=r"^-?\d{1,20}$")]


class UserCreate(BaseModel):
    email: Email
    password: Password


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    telegram_chat_id: str | None
    status_slug: str | None
    created_at: datetime


class UserUpdate(BaseModel):
    """Send null to clear a field. Fields that are not sent stay unchanged."""

    telegram_chat_id: TelegramChatId | None = None
    status_slug: StatusSlug | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

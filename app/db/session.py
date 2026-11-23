"""Database engine and session factory."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping checks a pooled connection before using it, so a restarted
# database does not cause "connection closed" errors (one cheap round trip).
# The pool is sized for the API's thread pool (40 threads by default): with the
# old default of 5 + 10 connections, threads queued for a connection under load.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed at the end."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

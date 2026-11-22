from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("monitors.id", ondelete="CASCADE")
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_up: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))


# History and stats queries always filter by monitor and sort by time (newest first).
Index(
    "ix_check_results_monitor_id_checked_at",
    CheckResult.monitor_id,
    CheckResult.checked_at.desc(),
)

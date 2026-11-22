"""Import every model here so `Base.metadata` knows all tables (used by Alembic)."""

from app.models.check_result import CheckResult
from app.models.incident import Incident
from app.models.monitor import Monitor, MonitorStatus
from app.models.user import User

__all__ = ["CheckResult", "Incident", "Monitor", "MonitorStatus", "User"]

"""SQLAlchemy models for the Burndown plugin."""
from datetime import date as date_type, datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, UniqueConstraint

from ...db import Base

_UTC = timezone.utc


class BurndownSnapshot(Base):
    """Daily snapshot of sprint remaining work — one row per sprint per day."""

    __tablename__ = "plugin_burndown_snapshots"
    __table_args__ = (UniqueConstraint("sprint_id", "snapshot_date", name="uq_burndown_sprint_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    sprint_id = Column(Integer, nullable=False, index=True)
    sprint_name = Column(String(128), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    remaining_points = Column(Float, nullable=False, default=0)
    remaining_tickets = Column(Integer, nullable=False, default=0)
    total_points = Column(Float, nullable=False, default=0)
    total_tickets = Column(Integer, nullable=False, default=0)
    recorded_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sprint_id": self.sprint_id,
            "sprint_name": self.sprint_name,
            "date": self.snapshot_date.isoformat(),
            "remaining_points": self.remaining_points,
            "remaining_tickets": self.remaining_tickets,
            "total_points": self.total_points,
            "total_tickets": self.total_tickets,
        }

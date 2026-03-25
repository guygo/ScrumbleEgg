"""SQLAlchemy models for the Test Planning plugin."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from ...db import Base

_UTC = timezone.utc


class TestPlan(Base):
    """A named collection of test cases, optionally tied to a sprint."""

    __tablename__ = "plugin_test_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    sprint = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="draft")  # draft/active/closed
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "sprint": self.sprint,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TestCase(Base):
    """A single test case belonging to a TestPlan."""

    __tablename__ = "plugin_test_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(
        Integer,
        ForeignKey("plugin_test_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(500), nullable=False)
    steps = Column(Text, nullable=True)
    expected = Column(Text, nullable=True)
    ticket_key = Column(String(32), nullable=True)  # optional link to a ticket
    result = Column(String(20), nullable=False, default="pending")  # pending/pass/fail/blocked
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "title": self.title,
            "steps": self.steps,
            "expected": self.expected,
            "ticket_key": self.ticket_key,
            "result": self.result,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

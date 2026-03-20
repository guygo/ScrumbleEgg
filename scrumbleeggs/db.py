"""Database models and session factory for scrumbleeggs.

Designed for easy backend swapping: replace the SQLite URL with any
SQLAlchemy-compatible URL (PostgreSQL, MySQL, etc.) and the rest works unchanged.
"""
import enum
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

_UTC = timezone.utc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TicketType(str, enum.Enum):
    """Ticket classification types."""

    STORY = "story"
    BUG = "bug"
    TASK = "task"


class TicketStatus(str, enum.Enum):
    """Scrum board column states."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class Priority(str, enum.Enum):
    """Ticket priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Role(str, enum.Enum):
    """Author role — drives which extra fields are collected."""

    DEVELOPER = "developer"
    TESTER = "tester"


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class Sprint(Base):
    """Represents a scrum sprint container."""

    __tablename__ = "sprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    goal = Column(Text, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        """Serialize sprint to a plain dictionary.

        Returns:
            dict: Sprint data as key-value pairs.
        """
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Ticket(Base):
    """Core ticket entity with standard + role-specific fields."""

    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(20), unique=True, nullable=False, index=True)

    # Standard fields
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    ticket_type = Column(String(20), nullable=False, default=TicketType.TASK)
    status = Column(String(20), nullable=False, default=TicketStatus.BACKLOG, index=True)
    priority = Column(String(20), nullable=False, default=Priority.MEDIUM, index=True)
    assignee = Column(String(200), nullable=True, index=True)
    sprint = Column(String(200), nullable=True, index=True)
    story_points = Column(Integer, nullable=True)
    role = Column(String(20), nullable=True)

    # Developer-specific fields
    acceptance_criteria = Column(Text, nullable=True)
    dev_checklist = Column(JSON, nullable=True)  # list[{item: str, done: bool}]

    # Tester-specific fields
    qa_notes = Column(Text, nullable=True)
    test_cases = Column(JSON, nullable=True)  # list[{name, steps, expected, status}]
    test_plan = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(_UTC), onupdate=lambda: datetime.now(_UTC))

    __table_args__ = (
        Index("ix_tickets_status_sprint", "status", "sprint"),
        Index("ix_tickets_assignee_status", "assignee", "status"),
        Index("ix_tickets_type_priority", "ticket_type", "priority"),
    )

    def to_dict(self) -> dict:
        """Serialize ticket to a plain dictionary.

        Returns:
            dict: Ticket data as key-value pairs.
        """
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "ticket_type": self.ticket_type,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
            "sprint": self.sprint,
            "story_points": self.story_points,
            "role": self.role,
            "acceptance_criteria": self.acceptance_criteria,
            "dev_checklist": self.dev_checklist,
            "qa_notes": self.qa_notes,
            "test_cases": self.test_cases,
            "test_plan": self.test_plan,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _on_connect(dbapi_conn, _connection_record) -> None:
    """Configure SQLite for multi-user WAL mode on each new connection."""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA busy_timeout=5000")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


def create_engine_from_url(db_url: str):
    """Build a SQLAlchemy engine with sane defaults for the given URL.

    Args:
        db_url: SQLAlchemy database URL string.

    Returns:
        Engine: Configured SQLAlchemy engine.
    """
    if db_url.startswith("sqlite"):
        if "///" in db_url and ":memory:" not in db_url:
            db_path = Path(db_url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)

        pool_args = {"poolclass": StaticPool} if ":memory:" in db_url else {}
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            **pool_args,
        )
        event.listen(engine, "connect", _on_connect)
    else:
        engine = create_engine(db_url)

    logger.debug("Engine created for: %s", db_url.split("@")[-1])
    return engine


# ---------------------------------------------------------------------------
# Database facade
# ---------------------------------------------------------------------------


class Database:
    """Thin facade over SQLAlchemy — swap the URL to change backends.

    Args:
        db_url: SQLAlchemy connection URL.
    """

    def __init__(self, db_url: str) -> None:
        self.engine = create_engine_from_url(db_url)
        self._SessionFactory = sessionmaker(self.engine, expire_on_commit=False)

    def create_tables(self) -> None:
        """Create all tables if they do not already exist."""
        Base.metadata.create_all(self.engine)
        logger.info("Database tables ensured.")

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Yield a transactional database session.

        Yields:
            Session: Active SQLAlchemy session — commits on success, rolls back on error.

        Raises:
            Exception: Re-raises any exception after rolling back.
        """
        session: Session = self._SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    event,
    text,
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


class ProjectStatus(str, enum.Enum):
    """Project lifecycle state."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class Project(Base):
    """A named container grouping related tickets."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(60), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    color = Column(String(20), default="#5e6ad2")
    status = Column(String(20), nullable=False, default=ProjectStatus.ACTIVE)
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "color": self.color,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Sprint(Base):
    """Represents a scrum sprint container."""

    __tablename__ = "sprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    goal = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String(32), nullable=False, default="active")
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
            "status": self.status or "active",
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class FieldType(str, enum.Enum):
    """Data type of a custom field."""
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    CHECKBOX = "checkbox"


class CustomFieldDef(Base):
    """Admin-defined custom field definition."""

    __tablename__ = "custom_field_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    key = Column(String(60), unique=True, nullable=False, index=True)
    field_type = Column(String(20), nullable=False, default=FieldType.TEXT)
    options = Column(JSON, nullable=True)   # list[str] for select type
    required = Column(Integer, default=0)   # 0=false, 1=true
    position = Column(Integer, default=0)   # display order
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "field_type": self.field_type,
            "options": self.options,
            "required": bool(self.required),
            "position": self.position,
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
    project = Column(String(200), nullable=True, index=True)
    story_points = Column(Integer, nullable=True)
    due_date = Column(String(10), nullable=True)  # ISO date string YYYY-MM-DD
    role = Column(String(20), nullable=True)

    # Developer-specific fields
    acceptance_criteria = Column(Text, nullable=True)
    dev_checklist = Column(JSON, nullable=True)  # list[{item: str, done: bool}]

    # Tester-specific fields
    qa_notes = Column(Text, nullable=True)
    test_cases = Column(JSON, nullable=True)  # list[{name, steps, expected, status}]
    test_plan = Column(Text, nullable=True)

    # Admin custom fields data
    custom_data = Column(JSON, nullable=True)  # dict[str, Any]

    is_template = Column(Integer, default=0)  # 1 = this ticket is a template
    # Subtask support
    parent_key = Column(String(32), ForeignKey("tickets.key"), nullable=True)

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
            "project": self.project,
            "story_points": self.story_points,
            "due_date": self.due_date,
            "role": self.role,
            "acceptance_criteria": self.acceptance_criteria,
            "dev_checklist": self.dev_checklist,
            "qa_notes": self.qa_notes,
            "test_cases": self.test_cases,
            "test_plan": self.test_plan,
            "custom_data": self.custom_data,
            "is_template": bool(self.is_template),
            "parent_key": self.parent_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_key = Column(String(32), ForeignKey("tickets.key"), nullable=False)
    author = Column(String(128), nullable=False, default="anonymous")
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_key": self.ticket_key,
            "author": self.author,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TicketRelation(Base):
    __tablename__ = "ticket_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_key = Column(String(32), nullable=False)
    to_key = Column(String(32), nullable=False)
    relation_type = Column(String(32), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_key": self.from_key,
            "to_key": self.to_key,
            "relation_type": self.relation_type,
        }


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_key = Column(String(32), nullable=False)
    author = Column(String(128), default="anonymous")
    minutes = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    logged_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_key": self.ticket_key,
            "author": self.author,
            "minutes": self.minutes,
            "note": self.note,
            "logged_at": self.logged_at.isoformat() if self.logged_at else None,
        }


class TicketActivityLog(Base):
    """Immutable audit trail of changes made to a ticket."""

    __tablename__ = "ticket_activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_key = Column(String(32), nullable=False, index=True)
    actor = Column(String(128), nullable=False, default="system")
    action = Column(String(64), nullable=False)   # e.g. "created", "status_changed", "comment_added"
    field = Column(String(64), nullable=True)      # which field changed (when action="field_changed")
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(_UTC))

    def to_dict(self) -> dict:
        """Serialize activity log entry to a plain dictionary."""
        return {
            "id": self.id,
            "ticket_key": self.ticket_key,
            "actor": self.actor,
            "action": self.action,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------


class UserModel(Base):
    """Registered user account with bcrypt-hashed credentials."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(32), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="developer")
    is_active = Column(Integer, nullable=False, default=1)  # 1=true, 0=false
    created_at = Column(DateTime, nullable=False)
    last_login = Column(DateTime, nullable=True)


class SessionModel(Base):
    """Server-side session record tied to a UserModel."""

    __tablename__ = "sessions"

    token = Column(String(64), primary_key=True)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)


class LoginAttemptModel(Base):
    """Audit log of login attempts for rate-limiting."""

    __tablename__ = "login_attempts"

    id = Column(String(36), primary_key=True)
    username = Column(String(32), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    attempted_at = Column(DateTime, nullable=False, index=True)
    success = Column(Integer, nullable=False, default=0)  # 1=true, 0=false


class InviteModel(Base):
    """One-time invite token for new user onboarding (no self-registration)."""

    __tablename__ = "invites"

    token = Column(String(64), primary_key=True)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)  # None = not yet redeemed


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _on_connect(dbapi_conn, _connection_record) -> None:
    """Configure SQLite for performance and multi-user WAL mode."""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA busy_timeout=5000")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")       # safe with WAL, faster than FULL
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    dbapi_conn.execute("PRAGMA cache_size=-64000")         # 64 MB page cache (negative = KB)
    dbapi_conn.execute("PRAGMA mmap_size=268435456")       # 256 MB memory-mapped I/O
    dbapi_conn.execute("PRAGMA temp_store=MEMORY")         # temp tables in RAM
    dbapi_conn.execute("PRAGMA wal_autocheckpoint=1000")   # checkpoint every 1000 pages


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
        """Create all tables if they do not already exist, then run migrations."""
        Base.metadata.create_all(self.engine)
        self._migrate()
        logger.info("Database tables ensured.")

    def _migrate(self) -> None:
        """Apply incremental schema changes to existing databases."""
        migrations = [
            "ALTER TABLE tickets ADD COLUMN project TEXT",
            "ALTER TABLE tickets ADD COLUMN custom_data TEXT",
            "ALTER TABLE sprints ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        ]
        with self.engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass  # Column already exists — safe to ignore

            try:
                conn.execute(text(
                    "ALTER TABLE tickets ADD COLUMN parent_key VARCHAR(32) REFERENCES tickets(key)"
                ))
                conn.commit()
            except Exception:
                pass

            # Auth migrations
            for auth_sql in [
                "ALTER TABLE tickets ADD COLUMN created_by VARCHAR(36)",
                "ALTER TABLE tickets ADD COLUMN due_date TEXT",
                "ALTER TABLE tickets ADD COLUMN is_template INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    conn.execute(text(auth_sql))
                    conn.commit()
                except Exception:
                    pass

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

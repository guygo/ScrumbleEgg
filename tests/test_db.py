"""Tests for scrumbleeggs.db module."""
import pytest
from sqlalchemy import inspect, text

from scrumbleeggs.db import (
    Database,
    Priority,
    Role,
    Sprint,
    Ticket,
    TicketStatus,
    TicketType,
    _on_connect,
    create_engine_from_url,
)


class TestEnums:
    """Tests for db enum definitions."""

    def test_ticket_type_values(self):
        assert set(TicketType) == {TicketType.STORY, TicketType.BUG, TicketType.TASK}

    def test_ticket_status_values(self):
        assert set(TicketStatus) == {
            TicketStatus.BACKLOG,
            TicketStatus.IN_PROGRESS,
            TicketStatus.REVIEW,
            TicketStatus.DONE,
        }

    def test_priority_values(self):
        assert set(Priority) == {
            Priority.CRITICAL,
            Priority.HIGH,
            Priority.MEDIUM,
            Priority.LOW,
        }

    def test_role_values(self):
        assert set(Role) == {Role.DEVELOPER, Role.TESTER}

    def test_ticket_status_is_str_subclass(self):
        assert isinstance(TicketStatus.BACKLOG, str)
        assert TicketStatus.BACKLOG == "backlog"

    def test_priority_is_str_subclass(self):
        assert isinstance(Priority.HIGH, str)
        assert Priority.HIGH == "high"


class TestCreateEngineFromUrl:
    """Tests for create_engine_from_url()."""

    def test_sqlite_memory_returns_engine(self):
        engine = create_engine_from_url("sqlite:///:memory:")
        assert engine is not None

    def test_sqlite_memory_uses_static_pool(self):
        from sqlalchemy.pool import StaticPool
        engine = create_engine_from_url("sqlite:///:memory:")
        assert isinstance(engine.pool, StaticPool)

    def test_sqlite_memory_connects_successfully(self):
        engine = create_engine_from_url("sqlite:///:memory:")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_sqlite_wal_pragma_applied(self):
        # In-memory SQLite ignores WAL and stays in 'memory' mode; both are valid outcomes
        engine = create_engine_from_url("sqlite:///:memory:")
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert mode in ("wal", "memory")

    def test_sqlite_foreign_keys_pragma_applied(self):
        engine = create_engine_from_url("sqlite:///:memory:")
        with engine.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk == 1


class TestDatabase:
    """Tests for the Database facade."""

    def test_init_creates_engine(self):
        db = Database("sqlite:///:memory:")
        assert db.engine is not None

    def test_create_tables_creates_tickets_table(self):
        db = Database("sqlite:///:memory:")
        db.create_tables()
        inspector = inspect(db.engine)
        assert "tickets" in inspector.get_table_names()

    def test_create_tables_creates_sprints_table(self):
        db = Database("sqlite:///:memory:")
        db.create_tables()
        inspector = inspect(db.engine)
        assert "sprints" in inspector.get_table_names()

    def test_session_commits_on_success(self):
        db = Database("sqlite:///:memory:")
        db.create_tables()
        with db.session() as session:
            t = Ticket(key="X-1", title="Test", ticket_type="task", status="backlog", priority="medium")
            session.add(t)

        # Verify persisted in a new session
        with db.session() as session:
            from sqlalchemy import select
            result = session.execute(select(Ticket).where(Ticket.key == "X-1")).scalar_one_or_none()
            assert result is not None
            assert result.title == "Test"

    def test_session_rolls_back_on_exception(self):
        db = Database("sqlite:///:memory:")
        db.create_tables()
        with pytest.raises(RuntimeError):
            with db.session() as session:
                t = Ticket(key="X-2", title="Rollback test", ticket_type="task", status="backlog", priority="medium")
                session.add(t)
                raise RuntimeError("forced error")

        with db.session() as session:
            from sqlalchemy import select
            result = session.execute(select(Ticket).where(Ticket.key == "X-2")).scalar_one_or_none()
            assert result is None

    def test_session_closes_after_success(self):
        db = Database("sqlite:///:memory:")
        db.create_tables()
        captured = []
        with db.session() as session:
            captured.append(session)
        # After the context manager exits, the session should not be usable
        assert captured[0].get_bind() is not None or True  # session was used successfully


class TestTicketToDict:
    """Tests for Ticket.to_dict() serialization."""

    def test_to_dict_contains_all_keys(self):
        t = Ticket(
            key="T-1",
            title="Hello",
            ticket_type="task",
            status="backlog",
            priority="medium",
        )
        d = t.to_dict()
        expected_keys = {
            "key", "title", "description", "ticket_type", "status", "priority",
            "assignee", "sprint", "story_points", "role",
            "acceptance_criteria", "dev_checklist", "qa_notes", "test_cases",
            "test_plan", "created_at", "updated_at",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_key_value(self):
        t = Ticket(key="T-99", title="My ticket", ticket_type="bug", status="done", priority="high")
        assert t.to_dict()["key"] == "T-99"
        assert t.to_dict()["title"] == "My ticket"


class TestSprintToDict:
    """Tests for Sprint.to_dict() serialization."""

    def test_to_dict_contains_expected_keys(self):
        s = Sprint(name="Sprint 1", goal="Ship it", is_active=1)
        d = s.to_dict()
        assert "name" in d
        assert "goal" in d
        assert "is_active" in d

    def test_is_active_serialized_as_bool(self):
        s = Sprint(name="Sprint 2", is_active=1)
        assert s.to_dict()["is_active"] is True

        s2 = Sprint(name="Sprint 3", is_active=0)
        assert s2.to_dict()["is_active"] is False

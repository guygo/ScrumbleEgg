"""Shared pytest fixtures for scrumbleeggs tests."""
import pytest

from scrumbleeggs.db import Database, Priority, Role, Ticket, TicketStatus, TicketType
from scrumbleeggs.tickets import TicketCreate, TicketService
from scrumbleeggs.reports import ReportService


@pytest.fixture
def db():
    """In-memory SQLite database — isolated per test."""
    database = Database("sqlite:///:memory:")
    database.create_tables()
    return database


@pytest.fixture
def svc(db):
    """TicketService backed by the in-memory DB."""
    return TicketService(db, prefix="TEST")


@pytest.fixture
def report_svc(tmp_path):
    """ReportService writing to a temporary directory."""
    return ReportService(output_dir=tmp_path)


@pytest.fixture
def sample_create():
    """Minimal valid TicketCreate DTO."""
    return TicketCreate(
        title="Fix the login bug",
        ticket_type=TicketType.BUG,
        priority=Priority.HIGH,
        assignee="alice",
        sprint="Sprint 1",
        story_points=3,
        description="Users cannot log in after the 2.0 upgrade.",
    )


@pytest.fixture
def dev_create():
    """Developer TicketCreate with role-specific fields."""
    return TicketCreate(
        title="Implement OAuth flow",
        ticket_type=TicketType.STORY,
        priority=Priority.CRITICAL,
        role=Role.DEVELOPER,
        acceptance_criteria="Given a user, when they click login, then OAuth redirects them.",
        dev_checklist=[
            {"item": "Code written", "done": False},
            {"item": "Tests pass", "done": False},
        ],
    )


@pytest.fixture
def qa_create():
    """Tester TicketCreate with QA-specific fields."""
    return TicketCreate(
        title="QA: OAuth regression",
        ticket_type=TicketType.TASK,
        priority=Priority.HIGH,
        role=Role.TESTER,
        test_plan="Test all OAuth providers in staging.",
        test_cases=[
            {
                "name": "Happy path",
                "steps": "1. Click login",
                "expected": "Redirected to dashboard",
                "status": "pending",
            }
        ],
        qa_notes="Edge case: token expiry.",
    )


@pytest.fixture
def ticket(svc, sample_create):
    """A single persisted ticket ready for read/update/delete tests."""
    return svc.create(sample_create)

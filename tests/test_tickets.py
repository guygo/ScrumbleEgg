"""Tests for scrumbleeggs.tickets module."""
import pytest
from sqlalchemy.exc import IntegrityError
from unittest.mock import patch

from scrumbleeggs.db import Priority, Role, TicketStatus, TicketType
from scrumbleeggs.tickets import TicketCreate, TicketService, TicketUpdate


class TestTicketCreate:
    """Tests for the TicketCreate dataclass."""

    def test_required_title_only(self):
        dto = TicketCreate(title="Minimal")
        assert dto.title == "Minimal"
        assert dto.ticket_type == TicketType.TASK
        assert dto.priority == Priority.MEDIUM
        assert dto.story_points is None
        assert dto.dev_checklist == []

    def test_all_fields_set(self, sample_create):
        assert sample_create.title == "Fix the login bug"
        assert sample_create.ticket_type == TicketType.BUG
        assert sample_create.priority == Priority.HIGH
        assert sample_create.assignee == "alice"
        assert sample_create.story_points == 3


class TestTicketUpdate:
    """Tests for the TicketUpdate dataclass."""

    def test_all_none_by_default(self):
        dto = TicketUpdate()
        for val in vars(dto).values():
            assert val is None

    def test_partial_fields_set(self):
        dto = TicketUpdate(title="New Title", priority=Priority.CRITICAL)
        assert dto.title == "New Title"
        assert dto.priority == Priority.CRITICAL
        assert dto.assignee is None


class TestTicketServiceCreate:
    """Tests for TicketService.create()."""

    def test_creates_ticket_with_correct_key(self, svc, sample_create):
        ticket = svc.create(sample_create)
        assert ticket.key == "TEST-1"

    def test_second_ticket_increments_key(self, svc, sample_create):
        svc.create(sample_create)
        t2 = svc.create(TicketCreate(title="Second"))
        assert t2.key == "TEST-2"

    def test_creates_ticket_in_backlog(self, svc, sample_create):
        ticket = svc.create(sample_create)
        assert ticket.status == TicketStatus.BACKLOG

    def test_strips_whitespace_from_title(self, svc):
        ticket = svc.create(TicketCreate(title="  Padded  "))
        assert ticket.title == "Padded"

    def test_empty_title_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="cannot be empty"):
            svc.create(TicketCreate(title=""))

    def test_whitespace_only_title_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="cannot be empty"):
            svc.create(TicketCreate(title="   "))

    def test_empty_assignee_stored_as_none(self, svc):
        ticket = svc.create(TicketCreate(title="No Assignee", assignee=""))
        assert ticket.assignee is None

    def test_dev_fields_persisted(self, svc, dev_create):
        ticket = svc.create(dev_create)
        assert ticket.acceptance_criteria is not None
        assert ticket.dev_checklist is not None
        assert len(ticket.dev_checklist) == 2

    def test_qa_fields_persisted(self, svc, qa_create):
        ticket = svc.create(qa_create)
        assert ticket.test_plan is not None
        assert len(ticket.test_cases) == 1
        assert ticket.qa_notes == "Edge case: token expiry."

    def test_role_stored_correctly(self, svc, dev_create):
        ticket = svc.create(dev_create)
        assert ticket.role == Role.DEVELOPER

    def test_custom_prefix(self, db):
        svc = TicketService(db, prefix="PROJ")
        ticket = svc.create(TicketCreate(title="Custom prefix"))
        assert ticket.key.startswith("PROJ-")

    def test_integrity_error_retries_once(self, svc, sample_create):
        """Simulate a key collision: first session raises IntegrityError, second succeeds."""
        attempt_keys = []
        original_session = svc.db.session

        from contextlib import contextmanager

        call_count = 0

        @contextmanager
        def counting_session():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate collision on first attempt — must raise IntegrityError
                raise IntegrityError("UNIQUE constraint failed: tickets.key", None, None)
            # Second attempt uses the real session
            with original_session() as s:
                yield s

        with patch.object(svc.db, "session", counting_session):
            ticket = svc.create(sample_create)

        assert ticket is not None
        assert call_count == 2

    def test_integrity_error_raises_after_two_attempts(self, svc, sample_create):
        """Two consecutive IntegrityErrors bubble up after exhausting retries."""
        from contextlib import contextmanager

        @contextmanager
        def always_collision():
            raise IntegrityError("UNIQUE constraint failed: tickets.key", None, None)
            yield  # make it a generator

        with patch.object(svc.db, "session", always_collision):
            with pytest.raises(IntegrityError):
                svc.create(sample_create)


class TestTicketServiceGet:
    """Tests for TicketService.get()."""

    def test_get_existing_ticket(self, svc, ticket):
        result = svc.get(ticket.key)
        assert result is not None
        assert result.key == ticket.key

    def test_get_is_case_insensitive(self, svc, ticket):
        result = svc.get(ticket.key.lower())
        assert result is not None

    def test_get_nonexistent_returns_none(self, svc):
        assert svc.get("TEST-9999") is None


class TestTicketServiceUpdate:
    """Tests for TicketService.update()."""

    def test_update_title(self, svc, ticket):
        updated = svc.update(ticket.key, TicketUpdate(title="New Title"))
        assert updated.title == "New Title"

    def test_update_priority(self, svc, ticket):
        updated = svc.update(ticket.key, TicketUpdate(priority=Priority.CRITICAL))
        assert updated.priority == Priority.CRITICAL

    def test_update_assignee(self, svc, ticket):
        updated = svc.update(ticket.key, TicketUpdate(assignee="bob"))
        assert updated.assignee == "bob"

    def test_update_story_points(self, svc, ticket):
        updated = svc.update(ticket.key, TicketUpdate(story_points=8))
        assert updated.story_points == 8

    def test_none_fields_are_not_applied(self, svc, ticket):
        original_title = ticket.title
        svc.update(ticket.key, TicketUpdate(priority=Priority.LOW))
        result = svc.get(ticket.key)
        assert result.title == original_title

    def test_update_nonexistent_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.update("TEST-9999", TicketUpdate(title="Ghost"))

    def test_update_key_case_insensitive(self, svc, ticket):
        updated = svc.update(ticket.key.lower(), TicketUpdate(title="Lower key"))
        assert updated.title == "Lower key"


class TestTicketServiceTransition:
    """Tests for TicketService.transition()."""

    def test_transition_to_in_progress(self, svc, ticket):
        result = svc.transition(ticket.key, TicketStatus.IN_PROGRESS)
        assert result.status == TicketStatus.IN_PROGRESS

    def test_transition_to_done(self, svc, ticket):
        result = svc.transition(ticket.key, TicketStatus.DONE)
        assert result.status == TicketStatus.DONE

    def test_transition_persisted_after_reload(self, svc, ticket):
        svc.transition(ticket.key, TicketStatus.REVIEW)
        reloaded = svc.get(ticket.key)
        assert reloaded.status == TicketStatus.REVIEW

    def test_transition_nonexistent_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.transition("TEST-9999", TicketStatus.DONE)


class TestTicketServiceDelete:
    """Tests for TicketService.delete()."""

    def test_delete_existing_returns_true(self, svc, ticket):
        result = svc.delete(ticket.key)
        assert result is True

    def test_delete_removes_from_db(self, svc, ticket):
        svc.delete(ticket.key)
        assert svc.get(ticket.key) is None

    def test_delete_nonexistent_returns_false(self, svc):
        assert svc.delete("TEST-9999") is False

    def test_delete_case_insensitive(self, svc, ticket):
        assert svc.delete(ticket.key.lower()) is True


class TestTicketServiceListTickets:
    """Tests for TicketService.list_tickets()."""

    def _create_batch(self, svc):
        tickets = [
            TicketCreate(title="Bug A", ticket_type=TicketType.BUG, priority=Priority.HIGH, assignee="alice", sprint="S1"),
            TicketCreate(title="Story B", ticket_type=TicketType.STORY, priority=Priority.LOW, assignee="bob", sprint="S1"),
            TicketCreate(title="Task C", ticket_type=TicketType.TASK, priority=Priority.MEDIUM, assignee="alice", sprint="S2"),
        ]
        return [svc.create(t) for t in tickets]

    def test_list_all_tickets(self, svc):
        self._create_batch(svc)
        results, total = svc.list_tickets()
        assert total == 3
        assert len(results) == 3

    def test_list_filter_by_status(self, svc):
        created = self._create_batch(svc)
        svc.transition(created[0].key, TicketStatus.DONE)
        results, total = svc.list_tickets(status=TicketStatus.DONE)
        assert total == 1
        assert results[0].key == created[0].key

    def test_list_filter_by_assignee(self, svc):
        self._create_batch(svc)
        results, total = svc.list_tickets(assignee="alice")
        assert total == 2

    def test_list_filter_by_sprint(self, svc):
        self._create_batch(svc)
        results, total = svc.list_tickets(sprint="S2")
        assert total == 1
        assert results[0].title == "Task C"

    def test_list_filter_by_type(self, svc):
        self._create_batch(svc)
        results, total = svc.list_tickets(ticket_type=TicketType.BUG)
        assert total == 1

    def test_list_filter_by_priority(self, svc):
        self._create_batch(svc)
        results, total = svc.list_tickets(priority=Priority.LOW)
        assert total == 1

    def test_list_filter_by_role(self, svc, dev_create, qa_create):
        svc.create(dev_create)
        svc.create(qa_create)
        results, total = svc.list_tickets(role=Role.TESTER)
        assert total == 1
        assert results[0].role == Role.TESTER

    def test_pagination_page_1(self, svc):
        for i in range(5):
            svc.create(TicketCreate(title=f"Ticket {i}"))
        results, total = svc.list_tickets(page=1, page_size=2)
        assert total == 5
        assert len(results) == 2

    def test_pagination_last_page(self, svc):
        for i in range(5):
            svc.create(TicketCreate(title=f"Ticket {i}"))
        results, total = svc.list_tickets(page=3, page_size=2)
        assert total == 5
        assert len(results) == 1

    def test_empty_db_returns_zero(self, svc):
        results, total = svc.list_tickets()
        assert total == 0
        assert results == []


class TestTicketServiceBoardData:
    """Tests for TicketService.board_data()."""

    def test_empty_board_has_four_columns(self, svc):
        board = svc.board_data()
        assert len(board) == 4
        for col in board.values():
            assert col == []

    def test_ticket_appears_in_correct_column(self, svc, ticket):
        board = svc.board_data()
        # Compare by key — board_data() loads fresh objects from the DB
        keys = [t.key for t in board[TicketStatus.BACKLOG]]
        assert ticket.key in keys

    def test_moved_ticket_in_correct_column(self, svc, ticket):
        key = ticket.key
        svc.transition(key, TicketStatus.DONE)
        board = svc.board_data()
        assert key not in [t.key for t in board[TicketStatus.BACKLOG]]
        assert key in [t.key for t in board[TicketStatus.DONE]]

    def test_sprint_filter(self, svc):
        svc.create(TicketCreate(title="In Sprint", sprint="S1"))
        svc.create(TicketCreate(title="No Sprint"))
        board = svc.board_data(sprint="S1")
        total = sum(len(v) for v in board.values())
        assert total == 1

    def test_priority_order_critical_first(self, svc):
        """Critical tickets should appear before high, medium, low in the board."""
        svc.create(TicketCreate(title="Low prio", priority=Priority.LOW))
        svc.create(TicketCreate(title="Critical prio", priority=Priority.CRITICAL))
        svc.create(TicketCreate(title="High prio", priority=Priority.HIGH))

        board = svc.board_data()
        backlog = board[TicketStatus.BACKLOG]
        priorities = [t.priority for t in backlog]
        assert priorities.index(Priority.CRITICAL) < priorities.index(Priority.HIGH)
        assert priorities.index(Priority.HIGH) < priorities.index(Priority.LOW)

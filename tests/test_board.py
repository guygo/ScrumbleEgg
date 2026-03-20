"""Tests for scrumbleeggs.board rendering module."""
import pytest
from io import StringIO
from unittest.mock import patch

from rich.console import Console

from scrumbleeggs.board import _ticket_card, render_board, render_ticket_detail
from scrumbleeggs.db import Priority, Role, Ticket, TicketStatus, TicketType


def _make_ticket(
    key="T-1",
    title="Sample ticket",
    status=TicketStatus.BACKLOG,
    priority=Priority.MEDIUM,
    ticket_type=TicketType.TASK,
    assignee=None,
    story_points=None,
    role=None,
    **kwargs,
) -> Ticket:
    """Build an unsaved Ticket ORM object for rendering tests."""
    t = Ticket(
        key=key,
        title=title,
        status=status,
        priority=priority,
        ticket_type=ticket_type,
        assignee=assignee,
        story_points=story_points,
        role=role,
        **kwargs,
    )
    return t


def _empty_board() -> dict:
    return {
        TicketStatus.BACKLOG: [],
        TicketStatus.IN_PROGRESS: [],
        TicketStatus.REVIEW: [],
        TicketStatus.DONE: [],
    }


class TestTicketCard:
    """Tests for _ticket_card() string renderer."""

    def test_contains_ticket_key(self):
        t = _make_ticket(key="SBE-99")
        card = _ticket_card(t)
        assert "SBE-99" in card

    def test_contains_ticket_title(self):
        t = _make_ticket(title="My feature")
        card = _ticket_card(t)
        assert "My feature" in card

    def test_long_title_truncated(self):
        t = _make_ticket(title="A" * 60)
        card = _ticket_card(t)
        assert "…" in card

    def test_short_title_not_truncated(self):
        t = _make_ticket(title="Short")
        card = _ticket_card(t)
        assert "…" not in card

    def test_assignee_shown_when_set(self):
        t = _make_ticket(assignee="alice")
        card = _ticket_card(t)
        assert "alice" in card

    def test_assignee_absent_when_none(self):
        t = _make_ticket(assignee=None)
        card = _ticket_card(t)
        assert "👤" not in card

    def test_story_points_shown_when_set(self):
        t = _make_ticket(story_points=5)
        card = _ticket_card(t)
        assert "5pt" in card

    def test_story_points_absent_when_none(self):
        t = _make_ticket(story_points=None)
        card = _ticket_card(t)
        assert "pt" not in card

    def test_developer_icon_for_developer_role(self):
        t = _make_ticket(role="developer")
        card = _ticket_card(t)
        assert "💻" in card

    def test_tester_icon_for_tester_role(self):
        t = _make_ticket(role="tester")
        card = _ticket_card(t)
        assert "🧪" in card

    @pytest.mark.parametrize("priority", [
        Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW
    ])
    def test_priority_shown(self, priority):
        t = _make_ticket(priority=priority)
        card = _ticket_card(t)
        # Use .value since Python 3.12+ renders str enums as ClassName.MEMBER
        assert priority.value in card


class TestRenderBoard:
    """Tests for render_board() — no crash, correct output structure."""

    def _capture(self, board, sprint=None):
        buf = StringIO()
        c = Console(file=buf, force_terminal=False, width=200)
        with patch("scrumbleeggs.board.console", c):
            render_board(board, sprint=sprint)
        return buf.getvalue()

    def test_empty_board_does_not_crash(self):
        """Critical regression: max() on empty board must not raise."""
        board = _empty_board()
        output = self._capture(board)
        assert "SCRUMBLEEGGS" in output

    def test_board_shows_column_names(self):
        output = self._capture(_empty_board())
        assert "BACKLOG" in output
        assert "IN PROGRESS" in output
        assert "REVIEW" in output
        assert "DONE" in output

    def test_board_with_sprint_shows_sprint_name(self):
        output = self._capture(_empty_board(), sprint="Sprint 42")
        assert "Sprint 42" in output

    def test_board_shows_total_count(self):
        board = _empty_board()
        board[TicketStatus.BACKLOG].append(_make_ticket(key="T-1"))
        output = self._capture(board)
        assert "Total: 1" in output

    def test_board_shows_ticket_key(self):
        board = _empty_board()
        board[TicketStatus.IN_PROGRESS].append(_make_ticket(key="SBE-7"))
        output = self._capture(board)
        assert "SBE-7" in output

    def test_board_multiple_tickets_all_shown(self):
        board = _empty_board()
        for i in range(3):
            board[TicketStatus.BACKLOG].append(_make_ticket(key=f"T-{i}", title=f"Ticket {i}"))
        output = self._capture(board)
        assert "Ticket 0" in output
        assert "Ticket 2" in output


class TestRenderTicketDetail:
    """Tests for render_ticket_detail() — full detail view."""

    def _capture_detail(self, ticket):
        buf = StringIO()
        c = Console(file=buf, force_terminal=False, width=200)
        with patch("scrumbleeggs.board.console", c):
            render_ticket_detail(ticket)
        return buf.getvalue()

    def test_shows_ticket_key(self):
        t = _make_ticket(key="SBE-42")
        output = self._capture_detail(t)
        assert "SBE-42" in output

    def test_shows_ticket_title(self):
        t = _make_ticket(title="Detailed ticket")
        output = self._capture_detail(t)
        assert "Detailed ticket" in output

    def test_shows_description_when_set(self):
        t = _make_ticket()
        t.description = "Detailed description here"
        output = self._capture_detail(t)
        assert "Detailed description here" in output

    def test_shows_acceptance_criteria(self):
        t = _make_ticket(role="developer")
        t.acceptance_criteria = "Given X, when Y, then Z"
        output = self._capture_detail(t)
        assert "Given X, when Y, then Z" in output

    def test_shows_dev_checklist(self):
        t = _make_ticket(role="developer")
        t.dev_checklist = [{"item": "Write tests", "done": True}]
        output = self._capture_detail(t)
        assert "Write tests" in output

    def test_shows_test_plan(self):
        t = _make_ticket(role="tester")
        t.test_plan = "Regression plan v2"
        output = self._capture_detail(t)
        assert "Regression plan v2" in output

    def test_shows_qa_notes(self):
        t = _make_ticket(role="tester")
        t.qa_notes = "Check timeout edge case"
        output = self._capture_detail(t)
        assert "Check timeout edge case" in output

    def test_shows_test_cases(self):
        t = _make_ticket(role="tester")
        t.test_cases = [{"name": "TC-1", "steps": "Do X", "expected": "Y", "status": "pending"}]
        output = self._capture_detail(t)
        assert "TC-1" in output

    def test_no_description_section_when_none(self):
        t = _make_ticket()
        t.description = None
        output = self._capture_detail(t)
        assert "Description" not in output

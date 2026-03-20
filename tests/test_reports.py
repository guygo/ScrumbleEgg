"""Tests for scrumbleeggs.reports module."""
import json
from pathlib import Path

import pytest

from scrumbleeggs.db import Priority, TicketStatus, TicketType, Ticket
from scrumbleeggs.reports import ReportService, _md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ticket(
    key="T-1",
    title="Sample ticket",
    status=TicketStatus.BACKLOG,
    priority=Priority.MEDIUM,
    ticket_type=TicketType.TASK,
    assignee=None,
    story_points=None,
) -> Ticket:
    return Ticket(
        id=int(key.split("-")[1]),
        key=key,
        title=title,
        status=status,
        priority=priority,
        ticket_type=ticket_type,
        assignee=assignee,
        story_points=story_points,
    )


def _empty_board():
    return {
        TicketStatus.BACKLOG: [],
        TicketStatus.IN_PROGRESS: [],
        TicketStatus.REVIEW: [],
        TicketStatus.DONE: [],
    }


# ---------------------------------------------------------------------------
# _md helper
# ---------------------------------------------------------------------------

class TestMdEscaper:
    """Tests for the _md() markdown pipe-escaping helper."""

    def test_plain_string_unchanged(self):
        assert _md("hello world") == "hello world"

    def test_single_pipe_escaped(self):
        assert _md("a|b") == r"a\|b"

    def test_multiple_pipes_all_escaped(self):
        assert _md("a|b|c") == r"a\|b\|c"

    def test_non_string_converted(self):
        assert _md(42) == "42"

    def test_empty_string(self):
        assert _md("") == ""


# ---------------------------------------------------------------------------
# ReportService
# ---------------------------------------------------------------------------

class TestReportServiceInit:
    """Tests for ReportService initialization."""

    def test_output_dir_created(self, tmp_path):
        new_dir = tmp_path / "reports" / "nested"
        svc = ReportService(output_dir=new_dir)
        assert new_dir.exists()

    def test_default_output_dir_is_current(self):
        svc = ReportService()
        assert svc.output_dir == Path(".")


class TestExportJson:
    """Tests for ReportService.export_json()."""

    def test_creates_json_file(self, report_svc):
        path = report_svc.export_json([])
        assert path.exists()
        assert path.suffix == ".json"

    def test_custom_filename_used(self, report_svc):
        path = report_svc.export_json([], filename="custom.json")
        assert path.name == "custom.json"

    def test_auto_filename_has_timestamp(self, report_svc):
        path = report_svc.export_json([])
        assert "scrumbleeggs_export_" in path.name

    def test_json_structure(self, report_svc):
        tickets = [_make_ticket("T-1"), _make_ticket("T-2")]
        path = report_svc.export_json(tickets)
        data = json.loads(path.read_text())
        assert "exported_at" in data
        assert data["total"] == 2
        assert len(data["tickets"]) == 2

    def test_empty_ticket_list(self, report_svc):
        path = report_svc.export_json([])
        data = json.loads(path.read_text())
        assert data["total"] == 0
        assert data["tickets"] == []

    def test_ticket_dict_includes_key(self, report_svc):
        path = report_svc.export_json([_make_ticket("T-7")])
        data = json.loads(path.read_text())
        assert data["tickets"][0]["key"] == "T-7"

    def test_ticket_dict_includes_title(self, report_svc):
        t = _make_ticket("T-1", title="My feature")
        path = report_svc.export_json([t])
        data = json.loads(path.read_text())
        assert data["tickets"][0]["title"] == "My feature"

    def test_file_is_utf8(self, report_svc):
        t = _make_ticket("T-1", title="Café au lait")
        path = report_svc.export_json([t])
        content = path.read_text(encoding="utf-8")
        assert "Café au lait" in content


class TestSprintReport:
    """Tests for ReportService.sprint_report()."""

    def test_creates_markdown_file(self, report_svc):
        path = report_svc.sprint_report(_empty_board())
        assert path.exists()
        assert path.suffix == ".md"

    def test_custom_filename(self, report_svc):
        path = report_svc.sprint_report(_empty_board(), filename="custom.md")
        assert path.name == "custom.md"

    def test_sprint_name_in_report(self, report_svc):
        path = report_svc.sprint_report(_empty_board(), sprint="Sprint 5")
        content = path.read_text()
        assert "Sprint 5" in content

    def test_all_sprints_when_no_sprint(self, report_svc):
        path = report_svc.sprint_report(_empty_board())
        content = path.read_text()
        assert "All sprints" in content

    def test_completion_percentage_zero(self, report_svc):
        board = _empty_board()
        board[TicketStatus.BACKLOG].append(_make_ticket("T-1"))
        path = report_svc.sprint_report(board)
        content = path.read_text()
        assert "0.0%" in content

    def test_completion_percentage_100(self, report_svc):
        board = _empty_board()
        board[TicketStatus.DONE].append(_make_ticket("T-1"))
        path = report_svc.sprint_report(board)
        content = path.read_text()
        assert "100.0%" in content

    def test_empty_board_zero_total(self, report_svc):
        path = report_svc.sprint_report(_empty_board())
        content = path.read_text()
        assert "| Total Tickets | 0 |" in content

    def test_ticket_key_in_report(self, report_svc):
        board = _empty_board()
        board[TicketStatus.IN_PROGRESS].append(_make_ticket("T-42"))
        path = report_svc.sprint_report(board)
        assert "T-42" in path.read_text()

    def test_pipe_in_title_escaped(self, report_svc):
        board = _empty_board()
        board[TicketStatus.BACKLOG].append(_make_ticket("T-1", title="A|B title"))
        path = report_svc.sprint_report(board)
        content = path.read_text()
        assert r"A\|B title" in content

    def test_empty_columns_omitted(self, report_svc):
        board = _empty_board()
        path = report_svc.sprint_report(board)
        content = path.read_text()
        # No section header for empty statuses
        assert "## Backlog" not in content


class TestTicketReport:
    """Tests for ReportService.ticket_report()."""

    def test_creates_markdown_file(self, report_svc):
        t = _make_ticket("T-1")
        path = report_svc.ticket_report(t)
        assert path.exists()

    def test_default_filename_is_ticket_key(self, report_svc):
        t = _make_ticket("T-99")
        path = report_svc.ticket_report(t)
        assert path.name == "T-99.md"

    def test_custom_filename(self, report_svc):
        t = _make_ticket("T-1")
        path = report_svc.ticket_report(t, filename="my_ticket.md")
        assert path.name == "my_ticket.md"

    def test_key_in_report(self, report_svc):
        t = _make_ticket("T-55")
        path = report_svc.ticket_report(t)
        assert "T-55" in path.read_text()

    def test_title_in_report(self, report_svc):
        t = _make_ticket("T-1", title="Auth feature")
        path = report_svc.ticket_report(t)
        assert "Auth feature" in path.read_text()

    def test_pipe_in_title_escaped(self, report_svc):
        t = _make_ticket("T-1", title="A|B")
        path = report_svc.ticket_report(t)
        assert r"A\|B" in path.read_text()

    def test_description_section_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.description = "Detailed description"
        path = report_svc.ticket_report(t)
        assert "Detailed description" in path.read_text()

    def test_acceptance_criteria_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.acceptance_criteria = "Given X"
        path = report_svc.ticket_report(t)
        assert "Given X" in path.read_text()

    def test_dev_checklist_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.dev_checklist = [{"item": "Write tests", "done": True}]
        path = report_svc.ticket_report(t)
        content = path.read_text()
        assert "Write tests" in content
        assert "[x]" in content

    def test_unchecked_checklist_item(self, report_svc):
        t = _make_ticket("T-1")
        t.dev_checklist = [{"item": "Deploy", "done": False}]
        path = report_svc.ticket_report(t)
        assert "[ ]" in path.read_text()

    def test_test_plan_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.test_plan = "Regression plan"
        path = report_svc.ticket_report(t)
        assert "Regression plan" in path.read_text()

    def test_test_cases_table_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.test_cases = [{"name": "TC-1", "steps": "Step A", "expected": "OK", "status": "pending"}]
        path = report_svc.ticket_report(t)
        assert "TC-1" in path.read_text()

    def test_pipe_in_test_case_escaped(self, report_svc):
        t = _make_ticket("T-1")
        t.test_cases = [{"name": "A|B", "steps": "Do X", "expected": "Y", "status": "pass"}]
        path = report_svc.ticket_report(t)
        assert r"A\|B" in path.read_text()

    def test_qa_notes_shown(self, report_svc):
        t = _make_ticket("T-1")
        t.qa_notes = "Watch for race conditions"
        path = report_svc.ticket_report(t)
        assert "Watch for race conditions" in path.read_text()

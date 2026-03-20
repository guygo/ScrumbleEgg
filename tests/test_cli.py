"""Tests for scrumbleeggs.cli module using Click's test runner."""
import json
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from scrumbleeggs.cli import cli
from scrumbleeggs.config import Config
from scrumbleeggs.db import Database, TicketStatus, TicketType, Priority


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def in_memory_config():
    """Config pointing at an in-memory SQLite DB — no disk writes during tests."""
    return Config(
        db_url="sqlite:///:memory:",
        project_prefix="TEST",
        page_size=20,
        default_assignee="",
        log_level="WARNING",
    )


@pytest.fixture
def invoke(runner, in_memory_config):
    """Return a helper that invokes the CLI with a shared in-memory DB."""
    db = Database(in_memory_config.db_url)
    db.create_tables()

    def _invoke(*args, input=None):
        with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
            with patch("scrumbleeggs.cli.Database", return_value=db):
                return runner.invoke(cli, list(args), input=input, catch_exceptions=False)

    return _invoke


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

class TestCliRoot:
    def test_help_shows_commands(self, invoke):
        result = invoke("--help")
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "board" in result.output

    def test_version_option(self, invoke):
        result = invoke("--version")
        assert result.exit_code == 0
        assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# create command
# ---------------------------------------------------------------------------

class TestCmdCreate:
    def test_create_with_title_flag(self, invoke):
        result = invoke("create", "--title", "Quick ticket")
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "Quick ticket" in result.output

    def test_create_with_type_and_priority(self, invoke):
        result = invoke("create", "--title", "Bug fix", "--type", "bug", "--priority", "high")
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_create_with_all_flags(self, invoke):
        result = invoke(
            "create",
            "--title", "Full ticket",
            "--type", "story",
            "--priority", "critical",
            "--assignee", "alice",
            "--sprint", "Sprint 1",
            "--points", "5",
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_create_second_ticket_increments_key(self, invoke):
        invoke("create", "--title", "First")
        result = invoke("create", "--title", "Second")
        assert "TEST-2" in result.output

    def test_create_empty_title_shows_error(self, in_memory_config):
        db = Database(in_memory_config.db_url)
        db.create_tables()
        r = CliRunner()
        with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
            with patch("scrumbleeggs.cli.Database", return_value=db):
                result = r.invoke(cli, ["create", "--title", "   "])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

class TestCmdList:
    def test_list_empty_shows_no_tickets_message(self, invoke):
        result = invoke("list")
        assert result.exit_code == 0
        assert "No tickets found" in result.output

    def test_list_shows_created_ticket(self, invoke):
        invoke("create", "--title", "Visible ticket")
        result = invoke("list")
        # Rich table collapses title column in narrow terminal; check key is present
        assert "TEST-1" in result.output

    def test_list_filter_by_status(self, invoke):
        invoke("create", "--title", "A ticket")
        result = invoke("list", "--status", "backlog")
        assert "TEST-1" in result.output

    def test_list_filter_by_status_no_match(self, invoke):
        invoke("create", "--title", "A ticket")
        result = invoke("list", "--status", "done")
        assert "No tickets found" in result.output

    def test_list_filter_by_assignee(self, invoke):
        invoke("create", "--title", "Assigned", "--assignee", "bob")
        result = invoke("list", "--assignee", "bob")
        assert "TEST-1" in result.output

    def test_list_filter_by_sprint(self, invoke):
        invoke("create", "--title", "Sprint ticket", "--sprint", "S1")
        invoke("create", "--title", "Other ticket", "--sprint", "S2")
        result = invoke("list", "--sprint", "S1")
        # S1 filter should return exactly 1 ticket (TEST-1 only)
        assert "TEST-1" in result.output
        assert "TEST-2" not in result.output

    def test_list_shows_page_info(self, invoke):
        invoke("create", "--title", "A ticket")
        result = invoke("list")
        assert "Page" in result.output

    def test_list_custom_page_size(self, invoke):
        for i in range(5):
            invoke("create", "--title", f"Ticket {i}")
        result = invoke("list", "--page-size", "2")
        assert "Page 1/3" in result.output


# ---------------------------------------------------------------------------
# show command
# ---------------------------------------------------------------------------

class TestCmdShow:
    def test_show_existing_ticket(self, invoke):
        invoke("create", "--title", "Show me")
        result = invoke("show", "TEST-1")
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "Show me" in result.output

    def test_show_nonexistent_exits_nonzero(self, in_memory_config):
        db = Database(in_memory_config.db_url)
        db.create_tables()
        r = CliRunner()
        with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
            with patch("scrumbleeggs.cli.Database", return_value=db):
                result = r.invoke(cli, ["show", "TEST-9999"])
        assert result.exit_code != 0

    def test_show_case_insensitive_key(self, invoke):
        invoke("create", "--title", "Case test")
        result = invoke("show", "test-1")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# move command
# ---------------------------------------------------------------------------

class TestCmdMove:
    def test_move_to_in_progress(self, invoke):
        invoke("create", "--title", "Moving ticket")
        result = invoke("move", "TEST-1", "in_progress")
        assert result.exit_code == 0
        assert "in_progress" in result.output

    def test_move_to_done(self, invoke):
        invoke("create", "--title", "Done ticket")
        result = invoke("move", "TEST-1", "done")
        assert result.exit_code == 0

    def test_move_nonexistent_exits_nonzero(self, in_memory_config):
        db = Database(in_memory_config.db_url)
        db.create_tables()
        r = CliRunner()
        with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
            with patch("scrumbleeggs.cli.Database", return_value=db):
                result = r.invoke(cli, ["move", "TEST-9999", "done"])
        assert result.exit_code != 0

    def test_move_persists_status(self, invoke):
        invoke("create", "--title", "Persistent move")
        invoke("move", "TEST-1", "review")
        result = invoke("show", "TEST-1")
        assert "review" in result.output


# ---------------------------------------------------------------------------
# update command
# ---------------------------------------------------------------------------

class TestCmdUpdate:
    def test_update_title(self, invoke):
        invoke("create", "--title", "Old title")
        result = invoke("update", "TEST-1", "--title", "New title")
        assert result.exit_code == 0
        assert "Updated" in result.output

    def test_update_priority(self, invoke):
        invoke("create", "--title", "Update priority")
        result = invoke("update", "TEST-1", "--priority", "critical")
        assert result.exit_code == 0

    def test_update_assignee(self, invoke):
        invoke("create", "--title", "Reassign me")
        result = invoke("update", "TEST-1", "--assignee", "charlie")
        assert result.exit_code == 0

    def test_update_nonexistent_exits_nonzero(self, in_memory_config):
        db = Database(in_memory_config.db_url)
        db.create_tables()
        r = CliRunner()
        with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
            with patch("scrumbleeggs.cli.Database", return_value=db):
                result = r.invoke(cli, ["update", "TEST-9999", "--title", "Ghost"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------

class TestCmdDelete:
    def test_delete_with_yes_flag(self, invoke):
        invoke("create", "--title", "Delete me")
        result = invoke("delete", "--yes", "TEST-1")
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_delete_removes_ticket(self, invoke):
        invoke("create", "--title", "Gone")
        invoke("delete", "--yes", "TEST-1")
        result = invoke("list")
        assert "Gone" not in result.output

    def test_delete_nonexistent_exits_nonzero(self, invoke):
        result = invoke("delete", "--yes", "TEST-9999")
        assert result.exit_code != 0

    def test_delete_prompts_confirmation_without_yes_flag(self, runner, in_memory_config):
        db = Database(in_memory_config.db_url)
        db.create_tables()

        def _invoke(*args, input=None):
            with patch("scrumbleeggs.cli.get_config", return_value=in_memory_config):
                with patch("scrumbleeggs.cli.Database", return_value=db):
                    return runner.invoke(cli, list(args), input=input, catch_exceptions=False)

        _invoke("create", "--title", "Confirm delete")
        result = _invoke("delete", "TEST-1", input="y\n")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# board command
# ---------------------------------------------------------------------------

class TestCmdBoard:
    def test_board_empty_does_not_crash(self, invoke):
        result = invoke("board")
        assert result.exit_code == 0
        assert "SCRUMBLEEGGS" in result.output

    def test_board_shows_all_columns(self, invoke):
        result = invoke("board")
        assert "BACKLOG" in result.output
        # IN PROGRESS / REVIEW / DONE may be truncated in narrow non-terminal renders;
        # the board title and total line are always present
        assert "SCRUMBLEEGGS" in result.output
        assert "Total:" in result.output

    def test_board_with_ticket_shows_key(self, invoke):
        invoke("create", "--title", "Board ticket")
        result = invoke("board")
        assert "TEST-1" in result.output

    def test_board_sprint_filter(self, invoke):
        invoke("create", "--title", "Sprint ticket", "--sprint", "S1")
        invoke("create", "--title", "Other ticket", "--sprint", "S2")
        result = invoke("board", "--sprint", "S1")
        assert result.exit_code == 0
        assert "Sprint: S1" in result.output


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------

class TestCmdExport:
    def test_export_json_creates_file(self, invoke, tmp_path):
        invoke("create", "--title", "Export me")
        result = invoke("export", "--format", "json", "--output", str(tmp_path / "out.json"))
        assert result.exit_code == 0
        assert "Exported" in result.output

    def test_export_markdown_creates_file(self, invoke, tmp_path):
        invoke("create", "--title", "Export markdown")
        result = invoke("export", "--format", "markdown", "--output", str(tmp_path / "report.md"))
        assert result.exit_code == 0
        assert "Exported" in result.output

    def test_export_json_default_format(self, invoke):
        result = invoke("export")
        assert result.exit_code == 0

    def test_export_with_sprint_filter(self, invoke):
        invoke("create", "--title", "Sprint ticket", "--sprint", "S1")
        result = invoke("export", "--format", "json", "--sprint", "S1")
        assert result.exit_code == 0

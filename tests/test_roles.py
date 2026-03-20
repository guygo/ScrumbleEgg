"""Tests for scrumbleeggs.roles module."""
import pytest
from unittest.mock import patch

from scrumbleeggs.db import Priority, Role, TicketType
from scrumbleeggs.roles import DeveloperWizard, TesterWizard, get_wizard
from scrumbleeggs.tickets import TicketCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_PROMPT_RESPONSES = [
    "My Ticket Title",  # Title
    "A description",    # Description
    "task",             # Type
    "medium",           # Priority
    "alice",            # Assignee
    "Sprint 1",         # Sprint
    "3",                # Story points
]


def _patch_base(extra_prompts=None):
    """Return a patch for click.prompt with base + optional extra responses."""
    responses = BASE_PROMPT_RESPONSES + (extra_prompts or [])
    return patch("scrumbleeggs.roles.click.prompt", side_effect=responses)


# ---------------------------------------------------------------------------
# DeveloperWizard
# ---------------------------------------------------------------------------

class TestDeveloperWizard:
    """Tests for DeveloperWizard."""

    def test_template_has_acceptance_criteria(self):
        t = DeveloperWizard.template()
        assert "acceptance_criteria" in t
        assert "Given" in t["acceptance_criteria"]

    def test_template_has_dev_checklist(self):
        t = DeveloperWizard.template()
        assert "dev_checklist" in t
        assert len(t["dev_checklist"]) > 0

    def test_template_checklist_items_have_correct_schema(self):
        for item in DeveloperWizard.template()["dev_checklist"]:
            assert "item" in item
            assert "done" in item
            assert item["done"] is False

    def test_run_returns_ticket_create(self):
        with _patch_base(["", ""]):  # extra prompts: custom item (blank=done)
            with patch("builtins.input", side_effect=["Given X", ""]):  # acceptance criteria
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):  # skip all defaults
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert isinstance(result, TicketCreate)

    def test_run_sets_developer_role(self):
        with _patch_base([""]):
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert result.role == Role.DEVELOPER

    def test_run_collects_acceptance_criteria(self):
        with _patch_base([""]):
            with patch("builtins.input", side_effect=["Given X When Y Then Z", ""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert "Given X When Y Then Z" in result.acceptance_criteria

    def test_run_includes_confirmed_checklist_items(self):
        with _patch_base([""]):  # empty custom item = done
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=True):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert len(result.dev_checklist) == len(DeveloperWizard.CHECKLIST_TEMPLATE)

    def test_run_skips_rejected_checklist_items(self):
        with _patch_base([""]):
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert len(result.dev_checklist) == 0

    def test_run_ticket_type_from_prompt(self):
        with _patch_base([""]):
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert result.ticket_type == TicketType.TASK

    def test_run_story_points_from_prompt(self):
        with _patch_base([""]):
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert result.story_points == 3

    def test_run_blank_story_points_gives_none(self):
        prompts = BASE_PROMPT_RESPONSES[:-1] + [""]  # replace "3" with ""
        with patch("scrumbleeggs.roles.click.prompt", side_effect=prompts + [""]):
            with patch("builtins.input", side_effect=[""]):
                with patch("scrumbleeggs.roles.click.confirm", return_value=False):
                    with patch("scrumbleeggs.roles.click.echo"):
                        result = DeveloperWizard().run()
        assert result.story_points is None


# ---------------------------------------------------------------------------
# TesterWizard
# ---------------------------------------------------------------------------

class TestTesterWizard:
    """Tests for TesterWizard."""

    def test_template_has_test_plan(self):
        t = TesterWizard.template()
        assert "test_plan" in t
        assert len(t["test_plan"]) > 0

    def test_template_has_test_cases(self):
        t = TesterWizard.template()
        assert "test_cases" in t
        assert len(t["test_cases"]) == 1

    def test_template_test_case_schema(self):
        tc = TesterWizard.template()["test_cases"][0]
        assert "name" in tc
        assert "steps" in tc
        assert "expected" in tc
        assert "status" in tc

    def test_template_has_qa_notes(self):
        t = TesterWizard.template()
        assert "qa_notes" in t

    def test_run_returns_ticket_create(self):
        with _patch_base(["0"]):  # 0 test cases
            with patch("builtins.input", side_effect=["", ""]):  # plan + qa notes = blank
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert isinstance(result, TicketCreate)

    def test_run_sets_tester_role(self):
        with _patch_base(["0"]):
            with patch("builtins.input", side_effect=["", ""]):
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert result.role == Role.TESTER

    def test_run_collects_test_plan(self):
        # Inputs: test plan content, test plan terminator, qa notes terminator
        with _patch_base(["0"]):
            with patch("builtins.input", side_effect=["Regression scope", "", ""]):
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert "Regression scope" in result.test_plan

    def test_run_zero_test_cases(self):
        with _patch_base(["0"]):
            with patch("builtins.input", side_effect=["", ""]):
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert result.test_cases == []

    def test_run_collects_test_cases(self):
        # Prompt responses: base fields + count "1" + TC name/steps/expected
        with _patch_base(["1", "Happy path", "Click login", "Redirected"]):
            with patch("builtins.input", side_effect=["", ""]):  # plan + qa notes
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert len(result.test_cases) == 1
        assert result.test_cases[0]["name"] == "Happy path"
        assert result.test_cases[0]["status"] == "pending"

    def test_run_collects_qa_notes(self):
        with _patch_base(["0"]):
            with patch("builtins.input", side_effect=["", "Token timeout edge case", ""]):
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert "Token timeout edge case" in result.qa_notes

    def test_run_invalid_count_defaults_to_zero(self):
        with _patch_base(["abc"]):  # non-digit count
            with patch("builtins.input", side_effect=["", ""]):
                with patch("scrumbleeggs.roles.click.echo"):
                    result = TesterWizard().run()
        assert result.test_cases == []


# ---------------------------------------------------------------------------
# get_wizard factory
# ---------------------------------------------------------------------------

class TestGetWizard:
    """Tests for the get_wizard() factory."""

    def test_developer_returns_developer_wizard(self):
        wizard = get_wizard("developer")
        assert isinstance(wizard, DeveloperWizard)

    def test_tester_returns_tester_wizard(self):
        wizard = get_wizard("tester")
        assert isinstance(wizard, TesterWizard)

    def test_unknown_role_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown role"):
            get_wizard("manager")

    def test_empty_role_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown role"):
            get_wizard("")

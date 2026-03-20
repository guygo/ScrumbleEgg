"""Role-specific ticket wizards and field templates for scrumbleeggs.

Two roles are supported:
  - developer: adds acceptance criteria and a dev checklist
  - tester:    adds a test plan, test cases, and QA notes
"""
import logging

import click

from .db import Priority, Role, TicketType
from .tickets import TicketCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared wizard helpers
# ---------------------------------------------------------------------------


def _prompt_base_fields(default_assignee: str = "") -> dict:
    """Prompt the user for the fields common to all ticket types.

    Args:
        default_assignee: Pre-fill the assignee field with this value.

    Returns:
        dict: Populated base field values.
    """
    title = click.prompt("Title")
    description = click.prompt("Description", default="", show_default=False)
    ticket_type = click.prompt(
        "Type",
        type=click.Choice([t.value for t in TicketType], case_sensitive=False),
        default=TicketType.TASK.value,
    )
    priority = click.prompt(
        "Priority",
        type=click.Choice([p.value for p in Priority], case_sensitive=False),
        default=Priority.MEDIUM.value,
    )
    assignee = click.prompt("Assignee", default=default_assignee, show_default=bool(default_assignee))
    sprint = click.prompt("Sprint", default="", show_default=False)
    story_points_raw = click.prompt("Story Points (blank to skip)", default="", show_default=False)
    story_points = int(story_points_raw) if story_points_raw.strip().isdigit() else None

    return {
        "title": title,
        "description": description,
        "ticket_type": TicketType(ticket_type),
        "priority": Priority(priority),
        "assignee": assignee,
        "sprint": sprint,
        "story_points": story_points,
    }


# ---------------------------------------------------------------------------
# Developer role wizard
# ---------------------------------------------------------------------------


class DeveloperWizard:
    """Interactive wizard for creating developer tickets.

    Collects standard fields plus acceptance criteria and a dev checklist.
    """

    CHECKLIST_TEMPLATE = [
        "Code written and self-reviewed",
        "Unit tests passing",
        "Integration tests passing",
        "Linting / mypy clean",
        "PR description updated",
        "Reviewed by peer",
    ]

    def run(self, default_assignee: str = "") -> TicketCreate:
        """Run the interactive developer ticket wizard.

        Args:
            default_assignee: Default value for the assignee prompt.

        Returns:
            TicketCreate: Populated DTO ready for TicketService.create().
        """
        click.echo("\n[Developer Ticket Wizard]\n")
        base = _prompt_base_fields(default_assignee)

        click.echo("\n-- Acceptance Criteria (blank line to finish) --")
        lines = []
        while True:
            line = input("> ")
            if not line:
                break
            lines.append(line)
        acceptance_criteria = "\n".join(lines)

        click.echo("\n-- Dev Checklist --")
        click.echo("Default checklist items (press Enter to keep, 'n' to skip each):")
        checklist = []
        for item in self.CHECKLIST_TEMPLATE:
            keep = click.confirm(f"  {item}?", default=True)
            if keep:
                checklist.append({"item": item, "done": False})

        click.echo("Add custom checklist items (blank to finish):")
        while True:
            custom = click.prompt("  Item", default="", show_default=False)
            if not custom.strip():
                break
            checklist.append({"item": custom.strip(), "done": False})

        return TicketCreate(
            **base,
            role=Role.DEVELOPER,
            acceptance_criteria=acceptance_criteria,
            dev_checklist=checklist,
        )

    @staticmethod
    def template() -> dict:
        """Return the default developer ticket field template.

        Returns:
            dict: Template showing all developer-specific field structures.
        """
        return {
            "acceptance_criteria": "Given ... When ... Then ...",
            "dev_checklist": [
                {"item": "Code written and self-reviewed", "done": False},
                {"item": "Unit tests passing", "done": False},
                {"item": "Integration tests passing", "done": False},
                {"item": "Linting / mypy clean", "done": False},
                {"item": "PR description updated", "done": False},
                {"item": "Reviewed by peer", "done": False},
            ],
        }


# ---------------------------------------------------------------------------
# Tester role wizard
# ---------------------------------------------------------------------------


class TesterWizard:
    """Interactive wizard for creating tester / QA tickets.

    Collects standard fields plus a test plan, test cases, and QA notes.
    """

    def run(self, default_assignee: str = "") -> TicketCreate:
        """Run the interactive tester ticket wizard.

        Args:
            default_assignee: Default value for the assignee prompt.

        Returns:
            TicketCreate: Populated DTO ready for TicketService.create().
        """
        click.echo("\n[Tester / QA Ticket Wizard]\n")
        base = _prompt_base_fields(default_assignee)

        click.echo("\n-- Test Plan (blank line to finish) --")
        lines = []
        while True:
            line = input("> ")
            if not line:
                break
            lines.append(line)
        test_plan = "\n".join(lines)

        click.echo("\n-- Test Cases (enter 0 to skip) --")
        test_cases = []
        count_raw = click.prompt("How many test cases?", default="0")
        count = int(count_raw) if count_raw.isdigit() else 0
        for i in range(count):
            click.echo(f"\nTest Case {i + 1}:")
            name = click.prompt("  Name")
            steps = click.prompt("  Steps")
            expected = click.prompt("  Expected result")
            test_cases.append({
                "name": name,
                "steps": steps,
                "expected": expected,
                "status": "pending",
            })

        click.echo("\n-- QA Notes (blank line to finish) --")
        notes_lines = []
        while True:
            line = input("> ")
            if not line:
                break
            notes_lines.append(line)
        qa_notes = "\n".join(notes_lines)

        return TicketCreate(
            **base,
            role=Role.TESTER,
            test_plan=test_plan,
            test_cases=test_cases,
            qa_notes=qa_notes,
        )

    @staticmethod
    def template() -> dict:
        """Return the default tester ticket field template.

        Returns:
            dict: Template showing all tester-specific field structures.
        """
        return {
            "test_plan": "Scope: ...\nApproach: ...\nEnvironment: ...\nRisks: ...",
            "test_cases": [
                {
                    "name": "Happy path",
                    "steps": "1. Do X\n2. Do Y",
                    "expected": "Z happens",
                    "status": "pending",
                }
            ],
            "qa_notes": "Observations, edge cases, environment notes...",
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_wizard(role: str) -> "DeveloperWizard | TesterWizard":
    """Return the appropriate wizard for the given role string.

    Args:
        role: Either 'developer' or 'tester'.

    Returns:
        DeveloperWizard or TesterWizard instance.

    Raises:
        ValueError: If role is not recognised.
    """
    if role == Role.DEVELOPER:
        return DeveloperWizard()
    if role == Role.TESTER:
        return TesterWizard()
    raise ValueError(f"Unknown role: {role!r}. Choose 'developer' or 'tester'.")

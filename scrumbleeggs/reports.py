"""Markdown and JSON report generation for scrumbleeggs."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_UTC = timezone.utc


def _md(value: str) -> str:
    """Escape pipe characters so a value is safe inside a markdown table cell."""
    return str(value).replace("|", "\\|")

from .db import Ticket, TicketStatus

logger = logging.getLogger(__name__)


class ReportService:
    """Generate markdown and JSON exports from ticket data.

    Args:
        output_dir: Directory where report files will be written.
    """

    def __init__(self, output_dir: Path = Path(".")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    def export_json(
        self,
        tickets: list[Ticket],
        filename: Optional[str] = None,
    ) -> Path:
        """Serialize tickets to a JSON file.

        Args:
            tickets: List of Ticket ORM objects to export.
            filename: Target filename; auto-generated with timestamp if omitted.

        Returns:
            Path: Absolute path of the written JSON file.
        """
        if not filename:
            ts = datetime.now(_UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"scrumbleeggs_export_{ts}.json"

        out_path = self.output_dir / filename
        data = {
            "exported_at": datetime.now(_UTC).isoformat(),
            "total": len(tickets),
            "tickets": [t.to_dict() for t in tickets],
        }
        out_path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        logger.info("JSON export written: %s", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Markdown reports
    # ------------------------------------------------------------------

    def sprint_report(
        self,
        board: dict[str, list[Ticket]],
        sprint: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """Generate a sprint summary markdown report.

        Args:
            board: Status -> tickets mapping from TicketService.board_data().
            sprint: Sprint name for the report header.
            filename: Target filename; auto-generated if omitted.

        Returns:
            Path: Absolute path of the written markdown file.
        """
        if not filename:
            ts = datetime.now(_UTC).strftime("%Y%m%d_%H%M%S")
            sprint_slug = sprint.replace(" ", "_") if sprint else "all"
            filename = f"sprint_report_{sprint_slug}_{ts}.md"

        all_tickets = [t for tickets in board.values() for t in tickets]
        total = len(all_tickets)
        done = len(board.get(TicketStatus.DONE, []))
        completion = round((done / total * 100) if total else 0, 1)

        lines = [
            f"# Scrumbleeggs Sprint Report",
            f"",
            f"**Sprint:** {sprint or 'All sprints'}  ",
            f"**Generated:** {datetime.now(_UTC).strftime('%Y-%m-%d %H:%M UTC')}  ",
            f"",
            f"## Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Tickets | {total} |",
            f"| Done | {done} |",
            f"| Completion | {completion}% |",
            f"| In Progress | {len(board.get(TicketStatus.IN_PROGRESS, []))} |",
            f"| In Review | {len(board.get(TicketStatus.REVIEW, []))} |",
            f"| Backlog | {len(board.get(TicketStatus.BACKLOG, []))} |",
            f"",
        ]

        for status, tickets in board.items():
            if not tickets:
                continue
            lines.append(f"## {status.replace('_', ' ').title()} ({len(tickets)})")
            lines.append("")
            lines.append("| Key | Title | Type | Priority | Assignee | Points |")
            lines.append("|-----|-------|------|----------|----------|--------|")
            for t in tickets:
                lines.append(
                    f"| {t.key} | {_md(t.title)} | {t.ticket_type} | "
                    f"{t.priority} | {_md(t.assignee or '—')} | {t.story_points or '—'} |"
                )
            lines.append("")

        out_path = self.output_dir / filename
        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Sprint report written: %s", out_path)
        return out_path

    def ticket_report(self, ticket: Ticket, filename: Optional[str] = None) -> Path:
        """Generate a detailed markdown file for a single ticket.

        Args:
            ticket: Ticket ORM object.
            filename: Target filename; defaults to <key>.md.

        Returns:
            Path: Absolute path of the written markdown file.
        """
        if not filename:
            filename = f"{ticket.key}.md"

        lines = [
            f"# {ticket.key}: {_md(ticket.title)}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Status | {ticket.status} |",
            f"| Type | {ticket.ticket_type} |",
            f"| Priority | {ticket.priority} |",
            f"| Assignee | {ticket.assignee or '—'} |",
            f"| Sprint | {ticket.sprint or '—'} |",
            f"| Story Points | {ticket.story_points or '—'} |",
            f"| Role | {ticket.role or '—'} |",
            f"| Created | {str(ticket.created_at)[:19] if ticket.created_at else '—'} |",
            f"",
        ]

        if ticket.description:
            lines += ["## Description", "", ticket.description, ""]

        if ticket.acceptance_criteria:
            lines += ["## Acceptance Criteria", "", ticket.acceptance_criteria, ""]

        if ticket.dev_checklist:
            lines += ["## Dev Checklist", ""]
            for item in ticket.dev_checklist:
                check = "x" if item.get("done") else " "
                lines.append(f"- [{check}] {item.get('item', '')}")
            lines.append("")

        if ticket.test_plan:
            lines += ["## Test Plan", "", ticket.test_plan, ""]

        if ticket.test_cases:
            lines += ["## Test Cases", ""]
            lines.append("| Name | Steps | Expected | Status |")
            lines.append("|------|-------|----------|--------|")
            for tc in ticket.test_cases:
                lines.append(
                    f"| {_md(tc.get('name', ''))} | {_md(tc.get('steps', ''))} | "
                    f"{_md(tc.get('expected', ''))} | {tc.get('status', 'pending')} |"
                )
            lines.append("")

        if ticket.qa_notes:
            lines += ["## QA Notes", "", ticket.qa_notes, ""]

        out_path = self.output_dir / filename
        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Ticket report written: %s", out_path)
        return out_path

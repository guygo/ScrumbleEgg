"""Scrum board terminal renderer using rich."""
import logging
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .db import Priority, Ticket, TicketStatus

logger = logging.getLogger(__name__)

console = Console()

# Column display config: status -> (label, border color)
COLUMNS = [
    (TicketStatus.BACKLOG, "BACKLOG", "bright_black"),
    (TicketStatus.IN_PROGRESS, "IN PROGRESS", "blue"),
    (TicketStatus.REVIEW, "REVIEW", "yellow"),
    (TicketStatus.DONE, "DONE", "green"),
]

PRIORITY_STYLES = {
    Priority.CRITICAL: "bold red",
    Priority.HIGH: "red",
    Priority.MEDIUM: "yellow",
    Priority.LOW: "dim white",
}

ROLE_ICONS = {
    "developer": "💻",
    "tester": "🧪",
}

TYPE_ICONS = {
    "story": "📖",
    "bug": "🐛",
    "task": "✅",
}


def _ticket_card(ticket: Ticket) -> str:
    """Render a single ticket as a multi-line string for a table cell.

    Args:
        ticket: Ticket ORM object.

    Returns:
        str: Rich-markup string representing the ticket card.
    """
    priority_val = ticket.priority.value if hasattr(ticket.priority, "value") else ticket.priority
    type_val = ticket.ticket_type.value if hasattr(ticket.ticket_type, "value") else ticket.ticket_type
    role_val = (ticket.role.value if hasattr(ticket.role, "value") else ticket.role) or ""
    priority_style = PRIORITY_STYLES.get(ticket.priority, "white")
    type_icon = TYPE_ICONS.get(type_val, "")
    role_icon = ROLE_ICONS.get(role_val, "")

    title = ticket.title
    if len(title) > 45:
        title = title[:44] + "…"

    lines = [
        f"[bold cyan]{ticket.key}[/bold cyan] {type_icon}{role_icon}",
        f"[white]{title}[/white]",
    ]
    if ticket.assignee:
        lines.append(f"[dim]👤 {ticket.assignee}[/dim]")
    pts = f"  [{ticket.story_points}pt]" if ticket.story_points else ""
    lines.append(f"[{priority_style}]⚑ {priority_val}{pts}[/{priority_style}]")
    return "\n".join(lines)


def render_board(
    board: dict[str, list[Ticket]],
    sprint: Optional[str] = None,
    max_per_column: int = 15,
) -> None:
    """Render a full scrum board to the terminal.

    Args:
        board: Mapping of status -> list of tickets from TicketService.board_data().
        sprint: Sprint name shown in the board title.
        max_per_column: Maximum tickets to display per column (prevents overflow).
    """
    title = "[bold magenta]SCRUMBLEEGGS[/bold magenta]"
    if sprint:
        title += f" [dim]— Sprint: {sprint}[/dim]"
    console.print(f"\n  {title}\n", justify="left")

    table = Table(
        show_header=True,
        header_style="bold",
        show_lines=True,
        expand=True,
        padding=(0, 1),
    )

    for _status, label, color in COLUMNS:
        tickets = board.get(_status, [])
        count = len(tickets)
        table.add_column(
            f"[bold {color}]{label} ({count})[/bold {color}]",
            style="",
            min_width=22,
        )

    # Build rows — one ticket per row across all columns simultaneously
    max_rows = max(
        (len(board.get(status, [])[:max_per_column]) for status, _, _ in COLUMNS),
        default=0,
    )

    for row_idx in range(max_rows):
        cells = []
        for status, _label, color in COLUMNS:
            tickets = board.get(status, [])
            if row_idx < len(tickets):
                card = _ticket_card(tickets[row_idx])
                cells.append(Panel(Text.from_markup(card), border_style=color, padding=(0, 1)))
            else:
                cells.append("")
        table.add_row(*cells)

    console.print(table)

    # Summary line
    total = sum(len(v) for v in board.values())
    done = len(board.get(TicketStatus.DONE, []))
    console.print(
        f"\n  [dim]Total: {total} tickets | Done: {done} | "
        f"Remaining: {total - done}[/dim]\n"
    )


def render_ticket_detail(ticket: Ticket) -> None:
    """Print full ticket details to the terminal.

    Args:
        ticket: Ticket ORM object.
    """
    type_icon = TYPE_ICONS.get(ticket.ticket_type, "")
    role_icon = ROLE_ICONS.get(ticket.role or "", "")
    priority_style = PRIORITY_STYLES.get(ticket.priority, "white")

    console.print()
    console.print(Panel(
        f"[bold cyan]{ticket.key}[/bold cyan]  {type_icon} {role_icon}  "
        f"[{priority_style}]⚑ {ticket.priority}[/{priority_style}]",
        title="[bold]Ticket Detail[/bold]",
        border_style="cyan",
    ))

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="dim", width=20)
    table.add_column("Value", style="white")

    rows = [
        ("Title", ticket.title),
        ("Status", ticket.status),
        ("Type", ticket.ticket_type),
        ("Priority", ticket.priority),
        ("Assignee", ticket.assignee or "—"),
        ("Sprint", ticket.sprint or "—"),
        ("Story Points", str(ticket.story_points) if ticket.story_points else "—"),
        ("Role", ticket.role or "—"),
        ("Created", str(ticket.created_at)[:19] if ticket.created_at else "—"),
        ("Updated", str(ticket.updated_at)[:19] if ticket.updated_at else "—"),
    ]
    for label, value in rows:
        table.add_row(label, value)

    console.print(table)

    if ticket.description:
        console.print(Panel(ticket.description, title="Description", border_style="dim"))

    if ticket.acceptance_criteria:
        console.print(
            Panel(ticket.acceptance_criteria, title="Acceptance Criteria", border_style="green")
        )

    if ticket.dev_checklist:
        lines = []
        for item in ticket.dev_checklist:
            check = "[x]" if item.get("done") else "[ ]"
            lines.append(f"{check} {item.get('item', '')}")
        console.print(Panel("\n".join(lines), title="Dev Checklist", border_style="blue"))

    if ticket.test_plan:
        console.print(Panel(ticket.test_plan, title="Test Plan", border_style="yellow"))

    if ticket.test_cases:
        tc_table = Table(title="Test Cases", show_header=True, header_style="bold yellow")
        tc_table.add_column("Name")
        tc_table.add_column("Steps")
        tc_table.add_column("Expected")
        tc_table.add_column("Status")
        for tc in ticket.test_cases:
            tc_table.add_row(
                tc.get("name", ""),
                tc.get("steps", ""),
                tc.get("expected", ""),
                tc.get("status", "pending"),
            )
        console.print(tc_table)

    if ticket.qa_notes:
        console.print(Panel(ticket.qa_notes, title="QA Notes", border_style="yellow"))

    console.print()

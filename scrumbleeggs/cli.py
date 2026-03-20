"""CLI entry point for scrumbleeggs (also aliased as 'sbe').

Usage examples:
    sbe create --role developer
    sbe create --role tester
    sbe list --status backlog --sprint "Sprint 1"
    sbe show SBE-5
    sbe move SBE-5 in_progress
    sbe board --sprint "Sprint 1"
    sbe export --format json
    sbe export --format markdown
    sbe delete SBE-5
"""
import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .board import render_board, render_ticket_detail
from .config import get_config
from .db import Database, Priority, Role, TicketStatus, TicketType
from .reports import ReportService
from .roles import get_wizard
from .tickets import TicketCreate, TicketService, TicketUpdate

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

STATUS_COLORS: dict[str, str] = {
    "backlog": "bright_black",
    "in_progress": "blue",
    "review": "yellow",
    "done": "green",
}
PRIORITY_COLORS: dict[str, str] = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "dim",
}


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _make_services(ctx: click.Context) -> tuple[TicketService, ReportService]:
    """Build service objects from Click context.

    Args:
        ctx: Click context carrying the shared Config.

    Returns:
        tuple[TicketService, ReportService]: Ready-to-use service instances.
    """
    config = ctx.obj["config"]
    db = ctx.obj["db"]
    ticket_svc = TicketService(db, prefix=config.project_prefix)
    report_svc = ReportService(output_dir=Path("."))
    return ticket_svc, report_svc


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.1.0", prog_name="scrumbleeggs")
@click.option("--debug", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """Scrumbleeggs (sbe) — local-first scrum board and ticket manager."""
    ctx.ensure_object(dict)
    config = get_config()
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    db = Database(config.db_url)
    db.create_tables()
    ctx.obj["config"] = config
    ctx.obj["db"] = db


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@cli.command("create")
@click.option(
    "--role",
    type=click.Choice(["developer", "tester"], case_sensitive=False),
    default=None,
    help="Use a role-specific wizard with extra fields.",
)
@click.option("--title", default=None, help="Ticket title (skip wizard).")
@click.option(
    "--type",
    "ticket_type",
    type=click.Choice([t.value for t in TicketType], case_sensitive=False),
    default=None,
)
@click.option(
    "--priority",
    type=click.Choice([p.value for p in Priority], case_sensitive=False),
    default=None,
)
@click.option("--assignee", default=None)
@click.option("--sprint", default=None)
@click.option("--points", "story_points", type=int, default=None)
@click.pass_context
def cmd_create(
    ctx: click.Context,
    role: Optional[str],
    title: Optional[str],
    ticket_type: Optional[str],
    priority: Optional[str],
    assignee: Optional[str],
    sprint: Optional[str],
    story_points: Optional[int],
) -> None:
    """Create a new ticket (interactive wizard or inline flags)."""
    ticket_svc, _ = _make_services(ctx)
    config = ctx.obj["config"]

    if role:
        wizard = get_wizard(role)
        data = wizard.run(default_assignee=config.default_assignee)
    elif title:
        data = TicketCreate(
            title=title,
            ticket_type=TicketType(ticket_type) if ticket_type else TicketType.TASK,
            priority=Priority(priority) if priority else Priority.MEDIUM,
            assignee=assignee or config.default_assignee,
            sprint=sprint or "",
            story_points=story_points,
        )
    else:
        # Generic interactive wizard
        from .roles import _prompt_base_fields
        base = _prompt_base_fields(config.default_assignee)
        data = TicketCreate(**base)

    try:
        ticket = ticket_svc.create(data)
        console.print(f"\n[bold green]Created:[/bold green] {ticket.key} — {ticket.title}\n")
    except Exception as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@cli.command("list")
@click.option("--status", type=click.Choice([s.value for s in TicketStatus], case_sensitive=False))
@click.option("--assignee")
@click.option("--sprint")
@click.option("--type", "ticket_type", type=click.Choice([t.value for t in TicketType], case_sensitive=False))
@click.option("--priority", type=click.Choice([p.value for p in Priority], case_sensitive=False))
@click.option("--role", type=click.Choice([r.value for r in Role], case_sensitive=False))
@click.option("--page", default=1, show_default=True, type=int)
@click.option("--page-size", default=None, type=int)
@click.pass_context
def cmd_list(
    ctx: click.Context,
    status: Optional[str],
    assignee: Optional[str],
    sprint: Optional[str],
    ticket_type: Optional[str],
    priority: Optional[str],
    role: Optional[str],
    page: int,
    page_size: Optional[int],
) -> None:
    """List tickets with optional filters."""
    ticket_svc, _ = _make_services(ctx)
    config = ctx.obj["config"]
    size = page_size or config.page_size

    tickets, total = ticket_svc.list_tickets(
        status=TicketStatus(status) if status else None,
        assignee=assignee,
        sprint=sprint,
        ticket_type=TicketType(ticket_type) if ticket_type else None,
        priority=Priority(priority) if priority else None,
        role=Role(role) if role else None,
        page=page,
        page_size=size,
    )

    if not tickets:
        console.print("[dim]No tickets found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Key", style="cyan", width=10)
    table.add_column("Title")
    table.add_column("Type", width=8)
    table.add_column("Status", width=12)
    table.add_column("Priority", width=10)
    table.add_column("Assignee", width=15)
    table.add_column("Sprint", width=12)
    table.add_column("Pts", width=4, justify="right")

    for t in tickets:
        sc = STATUS_COLORS.get(t.status, "white")
        pc = PRIORITY_COLORS.get(t.priority, "white")
        table.add_row(
            t.key,
            t.title[:60] + ("…" if len(t.title) > 60 else ""),
            t.ticket_type,
            f"[{sc}]{t.status}[/{sc}]",
            f"[{pc}]{t.priority}[/{pc}]",
            t.assignee or "—",
            t.sprint or "—",
            str(t.story_points) if t.story_points else "—",
        )

    console.print(table)
    pages = (total + size - 1) // size
    console.print(f"\n[dim]Page {page}/{pages} — {total} total tickets[/dim]\n")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@cli.command("show")
@click.argument("key")
@click.pass_context
def cmd_show(ctx: click.Context, key: str) -> None:
    """Show full details for a single ticket."""
    ticket_svc, _ = _make_services(ctx)
    ticket = ticket_svc.get(key)
    if not ticket:
        err_console.print(f"[bold red]Ticket {key.upper()} not found.[/bold red]")
        sys.exit(1)
    render_ticket_detail(ticket)


# ---------------------------------------------------------------------------
# move (transition)
# ---------------------------------------------------------------------------


@cli.command("move")
@click.argument("key")
@click.argument(
    "status",
    type=click.Choice([s.value for s in TicketStatus], case_sensitive=False),
)
@click.pass_context
def cmd_move(ctx: click.Context, key: str, status: str) -> None:
    """Move a ticket to a new status column.

    \b
    Valid statuses: backlog, in_progress, review, done
    """
    ticket_svc, _ = _make_services(ctx)
    try:
        ticket = ticket_svc.transition(key, TicketStatus(status))
        console.print(f"[bold green]Moved:[/bold green] {ticket.key} -> {ticket.status.value if hasattr(ticket.status, 'value') else ticket.status}")
    except ValueError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@cli.command("update")
@click.argument("key")
@click.option("--title")
@click.option("--description")
@click.option("--priority", type=click.Choice([p.value for p in Priority], case_sensitive=False))
@click.option("--assignee")
@click.option("--sprint")
@click.option("--points", "story_points", type=int)
@click.pass_context
def cmd_update(
    ctx: click.Context,
    key: str,
    title: Optional[str],
    description: Optional[str],
    priority: Optional[str],
    assignee: Optional[str],
    sprint: Optional[str],
    story_points: Optional[int],
) -> None:
    """Update fields on an existing ticket."""
    ticket_svc, _ = _make_services(ctx)
    data = TicketUpdate(
        title=title,
        description=description,
        priority=Priority(priority) if priority else None,
        assignee=assignee,
        sprint=sprint,
        story_points=story_points,
    )
    try:
        ticket = ticket_svc.update(key, data)
        console.print(f"[bold green]Updated:[/bold green] {ticket.key}")
    except ValueError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@cli.command("delete")
@click.argument("key")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def cmd_delete(ctx: click.Context, key: str, yes: bool) -> None:
    """Permanently delete a ticket."""
    ticket_svc, _ = _make_services(ctx)
    if not yes:
        click.confirm(f"Delete {key.upper()}? This cannot be undone.", abort=True)
    deleted = ticket_svc.delete(key)
    if deleted:
        console.print(f"[bold green]Deleted:[/bold green] {key.upper()}")
    else:
        err_console.print(f"[bold red]Ticket {key.upper()} not found.[/bold red]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# board
# ---------------------------------------------------------------------------


@cli.command("board")
@click.option("--sprint", default=None, help="Filter by sprint name.")
@click.pass_context
def cmd_board(ctx: click.Context, sprint: Optional[str]) -> None:
    """Display the scrum board with all four columns."""
    ticket_svc, _ = _make_services(ctx)
    board = ticket_svc.board_data(sprint=sprint)
    render_board(board, sprint=sprint)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@cli.command("export")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
)
@click.option("--sprint", default=None, help="Filter by sprint name.")
@click.option("--output", default=None, help="Output filename.")
@click.pass_context
def cmd_export(ctx: click.Context, fmt: str, sprint: Optional[str], output: Optional[str]) -> None:
    """Export tickets to JSON or Markdown."""
    ticket_svc, report_svc = _make_services(ctx)

    if fmt == "json":
        tickets, _ = ticket_svc.list_tickets(sprint=sprint, page_size=10_000)
        path = report_svc.export_json(tickets, filename=output)
    else:
        board = ticket_svc.board_data(sprint=sprint)
        path = report_svc.sprint_report(board, sprint=sprint, filename=output)

    console.print(f"[bold green]Exported:[/bold green] {path.resolve()}")


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------


@cli.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode).")
def cmd_web(host: str, port: int, reload: bool) -> None:
    """Launch the Scrumbleeggs web UI."""
    try:
        import uvicorn
    except ImportError:
        err_console.print(
            "[bold red]uvicorn not installed.[/bold red] "
            "Run: pip install 'scrumbleeggs[web]'"
        )
        sys.exit(1)

    console.print(
        f"[bold cyan]Scrumbleeggs Web UI[/bold cyan] starting at "
        f"[link]http://{host}:{port}[/link]"
    )
    uvicorn.run(
        "scrumbleeggs.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )

"""FastAPI web application for scrumbleeggs."""
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..config import get_config
from ..db import Database, Priority, Role, TicketStatus, TicketType
from ..tickets import TicketCreate, TicketService, TicketUpdate

logger = logging.getLogger(__name__)

_here = Path(__file__).parent

app = FastAPI(title="Scrumbleeggs", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))

# ---------------------------------------------------------------------------
# Shared dependency
# ---------------------------------------------------------------------------

_config = get_config()
_db = Database(_config.db_url)
_db.create_tables()
_svc = TicketService(_db, prefix=_config.project_prefix)


def get_svc() -> TicketService:
    return _svc


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class TicketCreateRequest(BaseModel):
    title: str
    description: str = ""
    ticket_type: str = "task"
    priority: str = "medium"
    assignee: str = ""
    sprint: str = ""
    story_points: Optional[int] = None
    role: Optional[str] = None
    acceptance_criteria: str = ""
    dev_checklist: list = []
    qa_notes: str = ""
    test_cases: list = []
    test_plan: str = ""


class TicketUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    sprint: Optional[str] = None
    story_points: Optional[int] = None
    acceptance_criteria: Optional[str] = None
    dev_checklist: Optional[list] = None
    qa_notes: Optional[str] = None
    test_cases: Optional[list] = None
    test_plan: Optional[str] = None


class MoveRequest(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def board_page(request: Request):
    """Render the main Kanban board page."""
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# API — Board
# ---------------------------------------------------------------------------


@app.get("/api/board")
async def api_board(sprint: Optional[str] = None):
    """Return tickets grouped by status for the board view."""
    board = _svc.board_data(sprint=sprint)
    return {
        status: [t.to_dict() for t in tickets]
        for status, tickets in board.items()
    }


# ---------------------------------------------------------------------------
# API — Tickets
# ---------------------------------------------------------------------------


@app.get("/api/tickets")
async def api_list(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    sprint: Optional[str] = None,
    ticket_type: Optional[str] = None,
    priority: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """List tickets with optional filters."""
    tickets, total = _svc.list_tickets(
        status=TicketStatus(status) if status else None,
        assignee=assignee,
        sprint=sprint,
        ticket_type=TicketType(ticket_type) if ticket_type else None,
        priority=Priority(priority) if priority else None,
        role=Role(role) if role else None,
        page=page,
        page_size=page_size,
    )
    return {"tickets": [t.to_dict() for t in tickets], "total": total}


@app.post("/api/tickets", status_code=201)
async def api_create(body: TicketCreateRequest):
    """Create a new ticket."""
    try:
        ticket = _svc.create(
            TicketCreate(
                title=body.title,
                description=body.description,
                ticket_type=TicketType(body.ticket_type),
                priority=Priority(body.priority),
                assignee=body.assignee,
                sprint=body.sprint,
                story_points=body.story_points,
                role=Role(body.role) if body.role else None,
                acceptance_criteria=body.acceptance_criteria,
                dev_checklist=body.dev_checklist,
                qa_notes=body.qa_notes,
                test_cases=body.test_cases,
                test_plan=body.test_plan,
            )
        )
        return ticket.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/tickets/{key}")
async def api_get(key: str):
    """Fetch a single ticket."""
    ticket = _svc.get(key)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
    return ticket.to_dict()


@app.patch("/api/tickets/{key}")
async def api_update(key: str, body: TicketUpdateRequest):
    """Partially update a ticket."""
    try:
        ticket = _svc.update(
            key,
            TicketUpdate(
                title=body.title,
                description=body.description,
                priority=Priority(body.priority) if body.priority else None,
                assignee=body.assignee,
                sprint=body.sprint,
                story_points=body.story_points,
                acceptance_criteria=body.acceptance_criteria,
                dev_checklist=body.dev_checklist,
                qa_notes=body.qa_notes,
                test_cases=body.test_cases,
                test_plan=body.test_plan,
            ),
        )
        return ticket.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/tickets/{key}/move")
async def api_move(key: str, body: MoveRequest):
    """Transition a ticket to a new status."""
    try:
        ticket = _svc.transition(key, TicketStatus(body.status))
        return ticket.to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/tickets/{key}", status_code=204)
async def api_delete(key: str):
    """Delete a ticket."""
    if not _svc.delete(key):
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------


@app.get("/api/stats")
async def api_stats():
    """Return summary statistics."""
    board = _svc.board_data()
    _, total = _svc.list_tickets(page_size=1)
    done = len(board.get(TicketStatus.DONE, []))
    in_progress = len(board.get(TicketStatus.IN_PROGRESS, []))
    backlog = len(board.get(TicketStatus.BACKLOG, []))
    return {
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "backlog": backlog,
        "completion_pct": round(done / total * 100 if total else 0, 1),
    }

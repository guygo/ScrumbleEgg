"""FastAPI web application for scrumbleeggs."""
import csv
import io
import logging
import os
import re
import time
from datetime import date as date_type
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select

from ..auth import AuthError, AuthService, RateLimitError, User
from ..config import get_config
from ..db import (
    CustomFieldDef, Database, FieldType, Priority, Project, ProjectStatus, Role,
    Sprint, TicketComment, TicketRelation, TicketStatus, TicketType, TimeEntry,
)
from ..tickets import TicketCreate, TicketService, TicketUpdate
from ..metrics import MetricsCollector

logger = logging.getLogger(__name__)

_here = Path(__file__).parent

# ---------------------------------------------------------------------------
# Auth bypass for automated testing (never enable in production)
# ---------------------------------------------------------------------------

_AUTH_DISABLED = os.getenv("SBE_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
_SESSION_COOKIE = "sbe_session"

# Public paths that never require authentication
_PUBLIC_PATHS = frozenset({"/login", "/auth/login", "/auth/logout", "/favicon.ico"})
_PUBLIC_PREFIXES = ("/static/",)

# Fake admin user injected when auth is disabled (testing only)
_ANON_ADMIN: Optional["User"] = None  # resolved lazily after User is imported

app = FastAPI(title="Scrumbleeggs", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=512)


# ---------------------------------------------------------------------------
# Auth middleware — runs before every request
# ---------------------------------------------------------------------------


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforce session authentication on all non-public routes.

    Sets ``request.state.user`` (User | None) for downstream handlers.
    Redirects unauthenticated page requests to /login and returns 401 for API calls.
    """
    path = request.url.path

    # Inject a fake admin when auth is globally disabled (CI / testing only)
    if _AUTH_DISABLED:
        from datetime import datetime, timezone
        request.state.user = User(
            id="00000000-0000-0000-0000-000000000000",
            username="ci-admin",
            email=None,
            role="admin",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        return await call_next(request)

    # Allow public routes through unconditionally
    is_public = (
        path in _PUBLIC_PATHS
        or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
    )

    if is_public:
        request.state.user = None
        return await call_next(request)

    token = request.cookies.get(_SESSION_COOKIE)
    user = _auth.get_session_user(token or "")
    request.state.user = user

    if user is None:
        # API callers get 401 JSON; browser requests get redirected to /login
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required."}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to every response (milliseconds)."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Process-Time"] = f"{elapsed_ms}ms"
    path = request.url.path
    if not path.startswith("/static") and path != "/api/perf/timeseries":
        _metrics.record(path, response.status_code, elapsed_ms)
    return response


app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))

# ---------------------------------------------------------------------------
# Shared singletons
# ---------------------------------------------------------------------------

_config = get_config()
_db = Database(_config.db_url)
_db.create_tables()
_svc = TicketService(_db, prefix=_config.project_prefix)
_auth = AuthService(_db)
_auth.bootstrap_admin()          # no-op if users already exist
_metrics = MetricsCollector(window=60)
_stats_cache: dict = {}
_board_cache: dict = {}
_STATS_TTL = 5.0
_BOARD_TTL = 1.0


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------


def get_current_user(request: Request) -> User:
    """FastAPI dependency — return the authenticated User or raise 401.

    Args:
        request: Incoming HTTP request (populated by auth middleware).

    Returns:
        Authenticated User object.

    Raises:
        HTTPException: 401 if no valid session is present.
    """
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """FastAPI dependency — require admin role.

    Args:
        current_user: Resolved by ``get_current_user``.

    Returns:
        The admin User.

    Raises:
        HTTPException: 403 if the user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


def _slug(name: str) -> str:
    """Convert a project name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


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
    project: str = ""
    story_points: Optional[int] = None
    role: Optional[str] = None
    acceptance_criteria: str = ""
    dev_checklist: list = []
    qa_notes: str = ""
    test_cases: list = []
    test_plan: str = ""
    custom_data: Optional[dict] = None


class TicketUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    sprint: Optional[str] = None
    project: Optional[str] = None
    story_points: Optional[int] = None
    acceptance_criteria: Optional[str] = None
    dev_checklist: Optional[list] = None
    qa_notes: Optional[str] = None
    test_cases: Optional[list] = None
    test_plan: Optional[str] = None
    custom_data: Optional[dict] = None


class MoveRequest(BaseModel):
    status: str


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    color: str = "#5e6ad2"


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None


class CustomFieldCreateRequest(BaseModel):
    name: str
    key: Optional[str] = None        # auto-derived from name if not provided
    field_type: str = "text"
    options: Optional[list] = None
    required: bool = False
    position: int = 0


class CustomFieldUpdateRequest(BaseModel):
    name: Optional[str] = None
    field_type: Optional[str] = None
    options: Optional[list] = None
    required: Optional[bool] = None
    position: Optional[int] = None


class CommentCreateRequest(BaseModel):
    author: Optional[str] = "anonymous"
    body: str


class RelationCreateRequest(BaseModel):
    to_key: str
    relation_type: str


class TimeEntryCreateRequest(BaseModel):
    author: Optional[str] = "anonymous"
    minutes: int
    note: Optional[str] = None


class SprintCreateRequest(BaseModel):
    name: str
    goal: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SprintUpdateRequest(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None


class SubtaskCreateRequest(BaseModel):
    title: str
    ticket_type: str = "task"
    priority: str = "medium"


class SetParentRequest(BaseModel):
    parent_key: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "developer"
    email: Optional[str] = None


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    email: Optional[str] = None
    password: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login form. Redirect to / if already authenticated."""
    token = request.cookies.get(_SESSION_COOKIE)
    if token and _auth.get_session_user(token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/auth/login")
async def auth_login(body: LoginRequest, request: Request, response: Response):
    """Authenticate a user and set a session cookie.

    Args:
        body: JSON body with ``username`` and ``password``.
        request: HTTP request (provides remote IP for audit).
        response: FastAPI response (used to set cookie).

    Returns:
        JSON with user data and redirect URL on success.

    Raises:
        HTTPException: 429 on rate limit, 401 on bad credentials.
    """
    ip = request.client.host if request.client else "unknown"
    try:
        _auth.check_rate_limit(body.username, ip)
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    user = _auth.get_user_by_username(body.username)
    if user is None or not user.is_active:
        _auth.record_login_attempt(body.username, ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    # Fetch hash from DB directly (User dataclass omits it)
    from ..db import UserModel
    with _db.session() as db:
        row = db.query(UserModel).filter_by(username=body.username).first()
        password_ok = _auth.verify_password(body.password, row.password_hash) if row else False

    if not password_ok:
        _auth.record_login_attempt(body.username, ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    _auth.record_login_attempt(body.username, ip, success=True)
    token = _auth.create_session(user.id, ip)

    response.set_cookie(
        key=_SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,  # 7 days
        secure=False,        # Set to True behind HTTPS in production
    )
    return {"user": user.to_dict(), "redirect": "/"}


@app.post("/auth/logout", status_code=204)
async def auth_logout(request: Request, response: Response):
    """Invalidate the current session cookie."""
    token = request.cookies.get(_SESSION_COOKIE)
    if token:
        _auth.delete_session(token)
    response.delete_cookie(_SESSION_COOKIE)


@app.get("/auth/me")
async def auth_me(current_user: CurrentUser):
    """Return the currently authenticated user's profile."""
    return current_user.to_dict()


# ---------------------------------------------------------------------------
# User management routes (admin only)
# ---------------------------------------------------------------------------


@app.get("/api/users")
async def list_users(_admin: AdminUser):
    """List all user accounts. Requires admin role."""
    return [u.to_dict() for u in _auth.list_users()]


@app.post("/api/users", status_code=201)
async def create_user(body: UserCreateRequest, _admin: AdminUser):
    """Create a new user account. Requires admin role."""
    try:
        user = _auth.create_user(
            username=body.username,
            password=body.password,
            role=body.role,
            email=body.email,
        )
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return user.to_dict()


@app.patch("/api/users/{user_id}")
async def update_user(user_id: str, body: UserUpdateRequest, _admin: AdminUser):
    """Update role, active status, email, or password for a user. Requires admin role."""
    try:
        user = _auth.update_user(
            user_id,
            role=body.role,
            is_active=body.is_active,
            email=body.email,
            password=body.password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return user.to_dict()


@app.delete("/api/users/{user_id}", status_code=204)
async def deactivate_user(user_id: str, current_user: CurrentUser, _admin: AdminUser):
    """Disable a user account (soft delete). Cannot deactivate yourself."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    try:
        _auth.update_user(user_id, is_active=False)
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def board_page(request: Request):
    """Main board/list/projects/stories SPA."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/tickets/{key}", response_class=HTMLResponse)
async def ticket_page(request: Request, key: str):
    """Full-page single ticket view (opens in new tab on double-click)."""
    ticket = _svc.get(key)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
    return templates.TemplateResponse(
        "ticket.html", {"request": request, "ticket": ticket.to_dict()}
    )


@app.get("/perf", response_class=HTMLResponse)
async def perf_page(request: Request):
    """Live performance dashboard."""
    return templates.TemplateResponse("perf.html", {"request": request})


@app.get("/chart-test", response_class=HTMLResponse)
async def chart_test_page(request: Request):
    """Simple Chart.js test page for debugging."""
    return templates.TemplateResponse("chart_test.html", {"request": request})


# ---------------------------------------------------------------------------
# API — Board
# ---------------------------------------------------------------------------


@app.get("/api/board")
async def api_board(sprint: Optional[str] = None, project: Optional[str] = None):
    """Return tickets grouped by status, with a 1-second TTL cache per filter combo."""
    global _board_cache
    now = time.time()
    cache_key = f"{sprint}:{project}"
    entry = _board_cache.get(cache_key)
    if entry and entry["expires"] > now:
        return entry["data"]

    board = _svc.board_data(sprint=sprint, project=project)
    data = {status: [t.to_dict() for t in tickets] for status, tickets in board.items()}
    _board_cache[cache_key] = {"data": data, "expires": now + _BOARD_TTL}
    # Evict stale keys to prevent unbounded growth
    _board_cache = {k: v for k, v in _board_cache.items() if v["expires"] > now}
    return data


# ---------------------------------------------------------------------------
# API — Tickets
# ---------------------------------------------------------------------------


@app.get("/api/tickets")
async def api_list(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    sprint: Optional[str] = None,
    project: Optional[str] = None,
    ticket_type: Optional[str] = None,
    priority: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    tickets, total = _svc.list_tickets(
        status=TicketStatus(status) if status else None,
        assignee=assignee,
        sprint=sprint,
        project=project,
        ticket_type=TicketType(ticket_type) if ticket_type else None,
        priority=Priority(priority) if priority else None,
        role=Role(role) if role else None,
        page=page,
        page_size=page_size,
    )
    return {"tickets": [t.to_dict() for t in tickets], "total": total}


@app.post("/api/tickets", status_code=201)
async def api_create(body: TicketCreateRequest):
    global _board_cache
    try:
        ticket = _svc.create(
            TicketCreate(
                title=body.title,
                description=body.description,
                ticket_type=TicketType(body.ticket_type),
                priority=Priority(body.priority),
                assignee=body.assignee,
                sprint=body.sprint,
                project=body.project,
                story_points=body.story_points,
                role=Role(body.role) if body.role else None,
                acceptance_criteria=body.acceptance_criteria,
                dev_checklist=body.dev_checklist,
                qa_notes=body.qa_notes,
                test_cases=body.test_cases,
                test_plan=body.test_plan,
                custom_data=body.custom_data,
            )
        )
        _board_cache.clear()  # Invalidate board cache so new ticket appears immediately
        return ticket.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/tickets/{key}")
async def api_get(key: str):
    ticket = _svc.get(key)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
    return ticket.to_dict()


@app.patch("/api/tickets/{key}")
async def api_update(key: str, body: TicketUpdateRequest):
    try:
        ticket = _svc.update(
            key,
            TicketUpdate(
                title=body.title,
                description=body.description,
                priority=Priority(body.priority) if body.priority else None,
                assignee=body.assignee,
                sprint=body.sprint,
                project=body.project,
                story_points=body.story_points,
                acceptance_criteria=body.acceptance_criteria,
                dev_checklist=body.dev_checklist,
                qa_notes=body.qa_notes,
                test_cases=body.test_cases,
                test_plan=body.test_plan,
                custom_data=body.custom_data,
            ),
        )
        return ticket.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/tickets/{key}/move")
async def api_move(key: str, body: MoveRequest):
    global _board_cache
    try:
        ticket = _svc.transition(key, TicketStatus(body.status))
        _board_cache.clear()
        return ticket.to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/tickets/{key}", status_code=204)
async def api_delete(key: str):
    global _board_cache
    if not _svc.delete(key):
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
    _board_cache.clear()


# ---------------------------------------------------------------------------
# API — Search
# ---------------------------------------------------------------------------


@app.get("/api/search")
async def api_search(q: str = "", page: int = 1, page_size: int = 20):
    if not q.strip():
        return {"tickets": [], "total": 0}
    tickets, total = _svc.search(q.strip(), page=page, page_size=page_size)
    return {"tickets": [t.to_dict() for t in tickets], "total": total}


# ---------------------------------------------------------------------------
# API — Comments
# ---------------------------------------------------------------------------


@app.get("/api/tickets/{key}/comments")
async def api_comments_list(key: str):
    with _db.session() as session:
        from ..db import Ticket as _Ticket
        t = session.execute(select(_Ticket).where(_Ticket.key == key.upper())).scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
        comments = list(
            session.execute(
                select(TicketComment)
                .where(TicketComment.ticket_key == key.upper())
                .order_by(TicketComment.created_at.asc())
            ).scalars()
        )
        return [c.to_dict() for c in comments]


@app.post("/api/tickets/{key}/comments", status_code=201)
async def api_comments_create(key: str, body: CommentCreateRequest):
    if not body.body.strip():
        raise HTTPException(status_code=422, detail="Comment body cannot be empty")
    with _db.session() as session:
        from ..db import Ticket as _Ticket
        t = session.execute(select(_Ticket).where(_Ticket.key == key.upper())).scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
        comment = TicketComment(
            ticket_key=key.upper(),
            author=body.author or "anonymous",
            body=body.body.strip(),
        )
        session.add(comment)
        session.flush()
        session.refresh(comment)
        return comment.to_dict()


@app.delete("/api/tickets/{key}/comments/{comment_id}", status_code=204)
async def api_comments_delete(key: str, comment_id: int):
    with _db.session() as session:
        comment = session.execute(
            select(TicketComment).where(
                TicketComment.id == comment_id,
                TicketComment.ticket_key == key.upper(),
            )
        ).scalar_one_or_none()
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")
        session.delete(comment)


# ---------------------------------------------------------------------------
# API — Relations
# ---------------------------------------------------------------------------


_VALID_RELATION_TYPES = {"blocks", "blocked_by", "relates_to", "duplicate_of"}


@app.get("/api/tickets/{key}/relations")
async def api_relations_list(key: str):
    from sqlalchemy import or_
    with _db.session() as session:
        relations = list(
            session.execute(
                select(TicketRelation).where(
                    or_(
                        TicketRelation.from_key == key.upper(),
                        TicketRelation.to_key == key.upper(),
                    )
                )
            ).scalars()
        )
        return [r.to_dict() for r in relations]


@app.post("/api/tickets/{key}/relations", status_code=201)
async def api_relations_create(key: str, body: RelationCreateRequest):
    if body.relation_type not in _VALID_RELATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"relation_type must be one of {sorted(_VALID_RELATION_TYPES)}",
        )
    with _db.session() as session:
        from ..db import Ticket as _Ticket
        t = session.execute(select(_Ticket).where(_Ticket.key == key.upper())).scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
        relation = TicketRelation(
            from_key=key.upper(),
            to_key=body.to_key.upper(),
            relation_type=body.relation_type,
        )
        session.add(relation)
        session.flush()
        session.refresh(relation)
        return relation.to_dict()


@app.delete("/api/tickets/{key}/relations/{relation_id}", status_code=204)
async def api_relations_delete(key: str, relation_id: int):
    from sqlalchemy import or_
    with _db.session() as session:
        relation = session.execute(
            select(TicketRelation).where(
                TicketRelation.id == relation_id,
                or_(
                    TicketRelation.from_key == key.upper(),
                    TicketRelation.to_key == key.upper(),
                ),
            )
        ).scalar_one_or_none()
        if not relation:
            raise HTTPException(status_code=404, detail="Relation not found")
        session.delete(relation)


# ---------------------------------------------------------------------------
# API — Time logging
# ---------------------------------------------------------------------------


@app.get("/api/tickets/{key}/time")
async def api_time_list(key: str):
    with _db.session() as session:
        from ..db import Ticket as _Ticket
        t = session.execute(select(_Ticket).where(_Ticket.key == key.upper())).scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
        entries = list(
            session.execute(
                select(TimeEntry)
                .where(TimeEntry.ticket_key == key.upper())
                .order_by(TimeEntry.logged_at.asc())
            ).scalars()
        )
        total_minutes = sum(e.minutes for e in entries)
        return {"entries": [e.to_dict() for e in entries], "total_minutes": total_minutes}


@app.post("/api/tickets/{key}/time", status_code=201)
async def api_time_create(key: str, body: TimeEntryCreateRequest):
    if body.minutes <= 0:
        raise HTTPException(status_code=422, detail="minutes must be a positive integer")
    with _db.session() as session:
        from ..db import Ticket as _Ticket
        t = session.execute(select(_Ticket).where(_Ticket.key == key.upper())).scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")
        entry = TimeEntry(
            ticket_key=key.upper(),
            author=body.author or "anonymous",
            minutes=body.minutes,
            note=body.note,
        )
        session.add(entry)
        session.flush()
        session.refresh(entry)
        return entry.to_dict()


@app.delete("/api/tickets/{key}/time/{entry_id}", status_code=204)
async def api_time_delete(key: str, entry_id: int):
    with _db.session() as session:
        entry = session.execute(
            select(TimeEntry).where(
                TimeEntry.id == entry_id,
                TimeEntry.ticket_key == key.upper(),
            )
        ).scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Time entry not found")
        session.delete(entry)


# ---------------------------------------------------------------------------
# API — Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects")
async def api_projects_list():
    """Return all projects with ticket counts (single JOIN query, no N+1)."""
    from ..db import Ticket
    from sqlalchemy import case as sa_case
    with _db.session() as session:
        stmt = (
            select(
                Project,
                func.count(Ticket.id).label("ticket_count"),
                func.sum(
                    sa_case((Ticket.status == TicketStatus.DONE, 1), else_=0)
                ).label("done_count"),
            )
            .select_from(Project)
            .outerjoin(Ticket, Ticket.project == Project.name)
            .group_by(Project.id)
            .order_by(Project.name)
        )
        rows = session.execute(stmt).all()
        result = []
        for proj, ticket_count, done_count in rows:
            d = proj.to_dict()
            d["ticket_count"] = ticket_count or 0
            d["done_count"] = done_count or 0
            result.append(d)
        return result


@app.post("/api/projects", status_code=201)
async def api_projects_create(body: ProjectCreateRequest):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Project name cannot be empty")
    slug = _slug(body.name)
    with _db.session() as session:
        from sqlalchemy.exc import IntegrityError
        try:
            proj = Project(
                name=body.name.strip(),
                slug=slug,
                description=body.description or None,
                color=body.color,
            )
            session.add(proj)
            session.flush()
            session.refresh(proj)
            return proj.to_dict()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"Project slug '{slug}' already exists")


@app.patch("/api/projects/{project_id}")
async def api_projects_update(project_id: int, body: ProjectUpdateRequest):
    with _db.session() as session:
        proj = session.get(Project, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        if body.name is not None:
            proj.name = body.name.strip()
        if body.description is not None:
            proj.description = body.description
        if body.color is not None:
            proj.color = body.color
        if body.status is not None:
            proj.status = body.status
        return proj.to_dict()


@app.delete("/api/projects/{project_id}", status_code=204)
async def api_projects_delete(project_id: int):
    with _db.session() as session:
        proj = session.get(Project, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        session.delete(proj)


# ---------------------------------------------------------------------------
# API — Sprints
# ---------------------------------------------------------------------------


def _parse_date(value: Optional[str]) -> Optional[date_type]:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {value!r}. Use YYYY-MM-DD.")


@app.get("/api/sprints")
async def api_sprints_list():
    with _db.session() as session:
        sprints = list(
            session.execute(
                select(Sprint).order_by(Sprint.created_at.desc())
            ).scalars()
        )
        return [s.to_dict() for s in sprints]


@app.post("/api/sprints", status_code=201)
async def api_sprints_create(body: SprintCreateRequest):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Sprint name cannot be empty")
    from sqlalchemy.exc import IntegrityError
    with _db.session() as session:
        try:
            sprint = Sprint(
                name=body.name.strip(),
                goal=body.goal or None,
                start_date=_parse_date(body.start_date),
                end_date=_parse_date(body.end_date),
                status="active",
            )
            session.add(sprint)
            session.flush()
            session.refresh(sprint)
            return sprint.to_dict()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"Sprint '{body.name}' already exists")


@app.patch("/api/sprints/{sprint_id}")
async def api_sprints_update(sprint_id: int, body: SprintUpdateRequest):
    with _db.session() as session:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        if body.name is not None:
            sprint.name = body.name.strip()
        if body.goal is not None:
            sprint.goal = body.goal
        if body.start_date is not None:
            sprint.start_date = _parse_date(body.start_date)
        if body.end_date is not None:
            sprint.end_date = _parse_date(body.end_date)
        if body.status is not None:
            sprint.status = body.status
        return sprint.to_dict()


@app.delete("/api/sprints/{sprint_id}", status_code=204)
async def api_sprints_delete(sprint_id: int):
    with _db.session() as session:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        session.delete(sprint)


@app.get("/api/sprints/{sprint_id}/stats")
async def api_sprints_stats(sprint_id: int):
    with _db.session() as session:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        from ..db import Ticket as _Ticket
        tickets = list(
            session.execute(
                select(_Ticket).where(_Ticket.sprint == sprint.name)
            ).scalars()
        )

    total_tickets = len(tickets)
    done_tickets = sum(1 for t in tickets if t.status == TicketStatus.DONE)
    total_points = sum(t.story_points or 0 for t in tickets)
    done_points = sum(t.story_points or 0 for t in tickets if t.status == TicketStatus.DONE)
    completion_pct = round(done_tickets / total_tickets * 100 if total_tickets else 0, 1)

    days_remaining = None
    if sprint.end_date:
        today = date_type.today()
        end = sprint.end_date if isinstance(sprint.end_date, date_type) else sprint.end_date.date()
        days_remaining = (end - today).days

    return {
        "name": sprint.name,
        "total_tickets": total_tickets,
        "done_tickets": done_tickets,
        "total_points": total_points,
        "done_points": done_points,
        "completion_pct": completion_pct,
        "days_remaining": days_remaining,
    }


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------


@app.get("/api/stats")
async def api_stats():
    global _stats_cache
    now = time.time()
    if _stats_cache.get("expires", 0) > now:
        return _stats_cache["data"]

    board = _svc.board_data()
    _, total = _svc.list_tickets(page_size=1)
    done = len(board.get(TicketStatus.DONE, []))
    in_progress = len(board.get(TicketStatus.IN_PROGRESS, []))
    backlog = len(board.get(TicketStatus.BACKLOG, []))
    data = {
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "backlog": backlog,
        "completion_pct": round(done / total * 100 if total else 0, 1),
    }
    _stats_cache = {"data": data, "expires": now + _STATS_TTL}
    return data


# ---------------------------------------------------------------------------
# API — Admin: Custom Fields
# ---------------------------------------------------------------------------


@app.get("/api/admin/fields")
async def api_admin_fields_list():
    """Return all custom field definitions ordered by position."""
    with _db.session() as session:
        fields = list(
            session.execute(
                select(CustomFieldDef).order_by(CustomFieldDef.position, CustomFieldDef.id)
            ).scalars()
        )
        return [f.to_dict() for f in fields]


@app.post("/api/admin/fields", status_code=201)
async def api_admin_fields_create(body: CustomFieldCreateRequest):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Field name cannot be empty")
    key = body.key or re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")
    with _db.session() as session:
        from sqlalchemy.exc import IntegrityError
        try:
            f = CustomFieldDef(
                name=body.name.strip(),
                key=key,
                field_type=body.field_type,
                options=body.options,
                required=1 if body.required else 0,
                position=body.position,
            )
            session.add(f)
            session.flush()
            session.refresh(f)
            return f.to_dict()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"Field key '{key}' already exists")


@app.patch("/api/admin/fields/{field_id}")
async def api_admin_fields_update(field_id: int, body: CustomFieldUpdateRequest):
    with _db.session() as session:
        f = session.get(CustomFieldDef, field_id)
        if not f:
            raise HTTPException(status_code=404, detail="Field not found")
        if body.name is not None:
            f.name = body.name.strip()
        if body.field_type is not None:
            f.field_type = body.field_type
        if body.options is not None:
            f.options = body.options
        if body.required is not None:
            f.required = 1 if body.required else 0
        if body.position is not None:
            f.position = body.position
        return f.to_dict()


@app.delete("/api/admin/fields/{field_id}", status_code=204)
async def api_admin_fields_delete(field_id: int):
    with _db.session() as session:
        f = session.get(CustomFieldDef, field_id)
        if not f:
            raise HTTPException(status_code=404, detail="Field not found")
        session.delete(f)


# ---------------------------------------------------------------------------
# API — Export
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ["key", "title", "status", "priority", "ticket_type", "assignee",
                "sprint", "project", "story_points", "created_at"]


@app.get("/api/export/csv")
async def api_export_csv(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    sprint: Optional[str] = None,
    assignee: Optional[str] = None,
    project: Optional[str] = None,
    ticket_type: Optional[str] = None,
):
    """Export filtered tickets as a CSV file download."""
    tickets, _ = _svc.list_tickets(
        status=TicketStatus(status) if status else None,
        assignee=assignee,
        sprint=sprint,
        project=project,
        ticket_type=TicketType(ticket_type) if ticket_type else None,
        priority=Priority(priority) if priority else None,
        page=1,
        page_size=100_000,
    )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for t in tickets:
        d = t.to_dict()
        writer.writerow({col: d.get(col, "") for col in _CSV_COLUMNS})

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )


@app.get("/api/export/json")
async def api_export_json(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    sprint: Optional[str] = None,
    assignee: Optional[str] = None,
    project: Optional[str] = None,
    ticket_type: Optional[str] = None,
):
    """Export filtered tickets as a JSON file download."""
    tickets, _ = _svc.list_tickets(
        status=TicketStatus(status) if status else None,
        assignee=assignee,
        sprint=sprint,
        project=project,
        ticket_type=TicketType(ticket_type) if ticket_type else None,
        priority=Priority(priority) if priority else None,
        page=1,
        page_size=100_000,
    )
    return JSONResponse(
        content=[t.to_dict() for t in tickets],
        headers={"Content-Disposition": "attachment; filename=tickets.json"},
    )


# ---------------------------------------------------------------------------
# API — Workload
# ---------------------------------------------------------------------------


@app.get("/api/workload")
async def api_workload():
    """Return per-assignee workload summary, sorted by in_progress count descending."""
    from ..db import Ticket as _Ticket

    with _db.session() as session:
        tickets = list(session.execute(select(_Ticket)).scalars())

    workload: dict[str, dict] = {}
    unassigned: dict = {
        "assignee": "Unassigned",
        "total": 0,
        "by_status": {"backlog": 0, "in_progress": 0, "review": 0, "done": 0},
        "story_points_total": 0,
        "story_points_done": 0,
    }

    for t in tickets:
        name = (t.assignee or "").strip()
        status_key = str(t.status).lower().replace(" ", "_")

        if not name:
            unassigned["total"] += 1
            if status_key in unassigned["by_status"]:
                unassigned["by_status"][status_key] += 1
            unassigned["story_points_total"] += t.story_points or 0
            if t.status == TicketStatus.DONE:
                unassigned["story_points_done"] += t.story_points or 0
            continue

        if name not in workload:
            workload[name] = {
                "assignee": name,
                "total": 0,
                "by_status": {"backlog": 0, "in_progress": 0, "review": 0, "done": 0},
                "story_points_total": 0,
                "story_points_done": 0,
            }
        workload[name]["total"] += 1
        if status_key in workload[name]["by_status"]:
            workload[name]["by_status"][status_key] += 1
        workload[name]["story_points_total"] += t.story_points or 0
        if t.status == TicketStatus.DONE:
            workload[name]["story_points_done"] += t.story_points or 0

    result = sorted(workload.values(), key=lambda x: x["by_status"]["in_progress"], reverse=True)
    result.append(unassigned)
    return result


# ---------------------------------------------------------------------------
# API — Subtasks
# ---------------------------------------------------------------------------


@app.get("/api/tickets/{key}/subtasks")
async def api_subtasks_list(key: str):
    """Return all tickets whose parent_key matches the given ticket key."""
    from ..db import Ticket as _Ticket

    with _db.session() as session:
        parent = session.execute(
            select(_Ticket).where(_Ticket.key == key.upper())
        ).scalar_one_or_none()
        if not parent:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")

        subtasks = list(
            session.execute(
                select(_Ticket).where(_Ticket.parent_key == key.upper())
            ).scalars()
        )
        return [t.to_dict() for t in subtasks]


@app.post("/api/tickets/{key}/subtasks", status_code=201)
async def api_subtasks_create(key: str, body: SubtaskCreateRequest):
    """Create a subtask under the given parent ticket."""
    from ..db import Ticket as _Ticket

    parent = _svc.get(key)
    if not parent:
        raise HTTPException(status_code=404, detail=f"Ticket {key} not found")

    try:
        ticket = _svc.create(
            TicketCreate(
                title=body.title,
                ticket_type=TicketType(body.ticket_type),
                priority=Priority(body.priority),
                sprint=parent.sprint or "",
                project=parent.project or "",
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Set parent_key after creation
    with _db.session() as session:
        t = session.execute(
            select(_Ticket).where(_Ticket.key == ticket.key)
        ).scalar_one()
        t.parent_key = key.upper()
        session.flush()
        session.refresh(t)
        return t.to_dict()


@app.patch("/api/tickets/{key}/parent")
async def api_set_parent(key: str, body: SetParentRequest):
    """Set or clear the parent_key of a ticket."""
    from ..db import Ticket as _Ticket

    with _db.session() as session:
        ticket = session.execute(
            select(_Ticket).where(_Ticket.key == key.upper())
        ).scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail=f"Ticket {key} not found")

        if body.parent_key is not None:
            parent = session.execute(
                select(_Ticket).where(_Ticket.key == body.parent_key.upper())
            ).scalar_one_or_none()
            if not parent:
                raise HTTPException(
                    status_code=404, detail=f"Parent ticket {body.parent_key} not found"
                )
            ticket.parent_key = body.parent_key.upper()
        else:
            ticket.parent_key = None

        session.flush()
        session.refresh(ticket)
        return ticket.to_dict()


# ---------------------------------------------------------------------------
# API — Burndown
# ---------------------------------------------------------------------------


@app.get("/api/sprints/{sprint_id}/burndown")
async def api_sprint_burndown(sprint_id: int):
    """Return burndown data for a sprint: ideal line, current remaining, and summary stats."""
    from ..db import Ticket as _Ticket

    with _db.session() as session:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        tickets = list(
            session.execute(
                select(_Ticket).where(_Ticket.sprint == sprint.name)
            ).scalars()
        )

    total_points = sum(t.story_points or 0 for t in tickets)
    done_points = sum(t.story_points or 0 for t in tickets if t.status == TicketStatus.DONE)
    today = date_type.today()

    start = sprint.start_date if sprint.start_date else today
    if not isinstance(start, date_type):
        start = start.date()

    end = sprint.end_date if sprint.end_date else today
    if not isinstance(end, date_type):
        end = end.date()

    days_total = max((end - start).days, 1)
    days_elapsed = max(min((today - start).days, days_total), 0)
    days_remaining = max(days_total - days_elapsed, 0)

    # Build ideal burndown line: one point per day from start to end
    from datetime import timedelta
    ideal_line = []
    for day_offset in range(days_total + 1):
        current_date = start + timedelta(days=day_offset)
        remaining = round(total_points * (1 - day_offset / days_total), 2)
        ideal_line.append({"date": current_date.isoformat(), "points": remaining})

    return {
        "sprint_id": sprint_id,
        "sprint_name": sprint.name,
        "total_points": total_points,
        "done_points": done_points,
        "days_total": days_total,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "ideal_line": ideal_line,
        "current": {
            "date": today.isoformat(),
            "remaining": total_points - done_points,
        },
    }


# ---------------------------------------------------------------------------
# API — Performance Diagnostics
# ---------------------------------------------------------------------------


@app.get("/api/perf")
async def api_perf():
    """Return DB and application performance diagnostics."""
    import platform, sys
    from sqlalchemy import text as sa_text

    diagnostics = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "db_url": _config.db_url.split("///")[-1],  # strip sqlite:///
        "pragma": {},
        "table_stats": {},
        "pool_info": {},
    }

    with _db.session() as session:
        # SQLite PRAGMA values
        for pragma in ["journal_mode", "synchronous", "cache_size", "page_size",
                       "mmap_size", "temp_store", "busy_timeout", "wal_autocheckpoint"]:
            try:
                val = session.execute(sa_text(f"PRAGMA {pragma}")).scalar()
                diagnostics["pragma"][pragma] = val
            except Exception:
                pass

        # Table row counts
        for table in ["tickets", "projects", "sprints", "custom_field_defs"]:
            try:
                count = session.execute(sa_text(f"SELECT COUNT(*) FROM {table}")).scalar()
                diagnostics["table_stats"][table] = count
            except Exception:
                diagnostics["table_stats"][table] = "n/a"

        # SQLite database size
        try:
            page_count = session.execute(sa_text("PRAGMA page_count")).scalar()
            page_size  = session.execute(sa_text("PRAGMA page_size")).scalar()
            diagnostics["db_size_bytes"] = (page_count or 0) * (page_size or 4096)
        except Exception:
            pass

    # SQLAlchemy pool info (if available)
    try:
        pool = _db.engine.pool
        diagnostics["pool_info"] = {
            "class": type(pool).__name__,
            "size": getattr(pool, "size", lambda: None)() if callable(getattr(pool, "size", None)) else getattr(pool, "_pool_size", "n/a"),
            "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else "n/a",
            "overflow": pool.overflow() if hasattr(pool, "overflow") else "n/a",
        }
    except Exception as e:
        diagnostics["pool_info"] = {"error": str(e)}

    return diagnostics


@app.get("/api/perf/timeseries")
async def api_perf_timeseries():
    """Return real-time time-series metrics for the dashboard."""
    data = _metrics.timeseries()
    # Attach current DB stats
    with _db.session() as session:
        from sqlalchemy import text as sa_text
        table_stats = {}
        for table in ["tickets", "projects", "custom_field_defs"]:
            try:
                table_stats[table] = session.execute(
                    sa_text(f"SELECT COUNT(*) FROM {table}")
                ).scalar()
            except Exception:
                table_stats[table] = 0
        try:
            page_count = session.execute(sa_text("PRAGMA page_count")).scalar()
            page_size  = session.execute(sa_text("PRAGMA page_size")).scalar()
            db_size = (page_count or 0) * (page_size or 4096)
        except Exception:
            db_size = 0
    data["db"] = {"table_stats": table_stats, "db_size_bytes": db_size}
    return data

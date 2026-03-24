"""Ticket CRUD and query operations for scrumbleeggs."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError

from .db import Database, Priority, Role, Ticket, TicketStatus, TicketType, Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class TicketCreate:
    """All fields required or optional when creating a new ticket.

    Attributes:
        title: Short summary of the ticket (required).
        ticket_type: Story, bug, or task.
        description: Detailed description.
        priority: Priority level.
        assignee: Team member responsible.
        sprint: Sprint name this ticket belongs to.
        story_points: Effort estimate.
        role: Author role (developer / tester) — controls extra fields.
        acceptance_criteria: Dev-role: definition of done.
        dev_checklist: Dev-role: ordered checklist items.
        qa_notes: Tester-role: general QA observations.
        test_cases: Tester-role: structured test case list.
        test_plan: Tester-role: overall test strategy.
    """

    title: str
    ticket_type: TicketType = TicketType.TASK
    description: str = ""
    priority: Priority = Priority.MEDIUM
    assignee: str = ""
    sprint: str = ""
    project: str = ""
    story_points: Optional[int] = None
    due_date: Optional[str] = None  # ISO date YYYY-MM-DD
    role: Optional[Role] = None
    # Developer fields
    acceptance_criteria: str = ""
    dev_checklist: list = field(default_factory=list)
    # Tester fields
    qa_notes: str = ""
    test_cases: list = field(default_factory=list)
    test_plan: str = ""
    # Admin custom fields
    custom_data: Optional[dict] = None


@dataclass
class TicketUpdate:
    """Partial update DTO — only non-None fields are applied.

    Attributes:
        title: New ticket title.
        description: New description.
        priority: New priority level.
        assignee: New assignee name.
        sprint: New sprint name.
        story_points: New story point estimate.
        acceptance_criteria: Updated acceptance criteria.
        dev_checklist: Updated dev checklist.
        qa_notes: Updated QA notes.
        test_cases: Updated test cases.
        test_plan: Updated test plan.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Priority] = None
    assignee: Optional[str] = None
    sprint: Optional[str] = None
    project: Optional[str] = None
    story_points: Optional[int] = None
    due_date: Optional[str] = None  # ISO date YYYY-MM-DD
    is_template: Optional[int] = None  # 0=false, 1=true
    acceptance_criteria: Optional[str] = None
    dev_checklist: Optional[list] = None
    qa_notes: Optional[str] = None
    test_cases: Optional[list] = None
    test_plan: Optional[str] = None
    custom_data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TicketService:
    """Create, read, update, delete, and query tickets.

    Args:
        db: Initialized Database instance.
        prefix: Project key prefix for ticket IDs.
    """

    def __init__(self, db: Database, prefix: str = "SBE") -> None:
        self.db = db
        self.prefix = prefix

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create(self, data: TicketCreate) -> Ticket:
        """Persist a new ticket and return it with its assigned key.

        Retries once on IntegrityError to handle concurrent key collisions
        under multi-user SQLite WAL mode.

        Args:
            data: TicketCreate DTO with all ticket field values.

        Returns:
            Ticket: The newly created and persisted ticket object.

        Raises:
            IntegrityError: If a key collision persists after one retry.
            ValueError: If the title is empty.
        """
        title = data.title.strip()
        if not title:
            raise ValueError("Ticket title cannot be empty.")

        key = f"{self.prefix}-?"
        for attempt in range(2):
            try:
                with self.db.session() as session:
                    max_id = session.execute(select(func.max(Ticket.id))).scalar() or 0
                    key = f"{self.prefix}-{max_id + 1}"

                    ticket = Ticket(
                        key=key,
                        title=title,
                        description=data.description or None,
                        ticket_type=data.ticket_type,
                        status=TicketStatus.BACKLOG,
                        priority=data.priority,
                        assignee=data.assignee or None,
                        sprint=data.sprint or None,
                        project=data.project or None,
                        story_points=data.story_points,
                        role=data.role,
                        acceptance_criteria=data.acceptance_criteria or None,
                        dev_checklist=data.dev_checklist or None,
                        qa_notes=data.qa_notes or None,
                        test_cases=data.test_cases or None,
                        test_plan=data.test_plan or None,
                        custom_data=data.custom_data,
                    )
                    session.add(ticket)
                    session.flush()
                    session.refresh(ticket)
                    logger.info("Created ticket %s: %s", ticket.key, ticket.title)
                    return ticket
            except IntegrityError:
                if attempt == 1:
                    raise
                logger.warning("Key collision on %s, retrying...", key)

        raise RuntimeError("Unreachable")

    def update(self, key: str, data: TicketUpdate) -> Ticket:
        """Apply partial updates to an existing ticket.

        Args:
            key: Ticket key (e.g. SBE-7).
            data: TicketUpdate DTO — only non-None fields are applied.

        Returns:
            Ticket: The updated ticket.

        Raises:
            ValueError: If no ticket with the given key exists.
        """
        with self.db.session() as session:
            ticket = session.execute(
                select(Ticket).where(Ticket.key == key.upper())
            ).scalar_one_or_none()
            if not ticket:
                raise ValueError(f"Ticket {key} not found.")

            for attr, value in vars(data).items():
                if value is not None:
                    setattr(ticket, attr, value)
            ticket.updated_at = datetime.now(timezone.utc)
            logger.info("Updated ticket %s", key)
            return ticket

    def transition(self, key: str, status: TicketStatus) -> Ticket:
        """Move a ticket to a new board column.

        Args:
            key: Ticket key.
            status: Target TicketStatus value.

        Returns:
            Ticket: The ticket after transition.

        Raises:
            ValueError: If no ticket with the given key exists.
        """
        with self.db.session() as session:
            ticket = session.execute(
                select(Ticket).where(Ticket.key == key.upper())
            ).scalar_one_or_none()
            if not ticket:
                raise ValueError(f"Ticket {key} not found.")
            old_status = ticket.status
            ticket.status = status
            ticket.updated_at = datetime.now(timezone.utc)
            logger.info("Transitioned %s: %s -> %s", key, old_status, status)
            return ticket

    def delete(self, key: str) -> bool:
        """Permanently delete a ticket.

        Args:
            key: Ticket key.

        Returns:
            bool: True if deleted, False if not found.
        """
        with self.db.session() as session:
            ticket = session.execute(
                select(Ticket).where(Ticket.key == key.upper())
            ).scalar_one_or_none()
            if not ticket:
                return False
            session.delete(ticket)
            logger.info("Deleted ticket %s", key)
            return True

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Ticket]:
        """Fetch a single ticket by its key.

        Args:
            key: Ticket key (e.g. SBE-5).

        Returns:
            Ticket or None if not found.
        """
        with self.db.session() as session:
            return session.execute(
                select(Ticket).where(Ticket.key == key.upper())
            ).scalar_one_or_none()

    def list_tickets(
        self,
        status: Optional[TicketStatus] = None,
        assignee: Optional[str] = None,
        sprint: Optional[str] = None,
        project: Optional[str] = None,
        ticket_type: Optional[TicketType] = None,
        priority: Optional[Priority] = None,
        role: Optional[Role] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Ticket], int]:
        """Query tickets with optional filters and pagination.

        Args:
            status: Filter by board column status.
            assignee: Filter by assignee name.
            sprint: Filter by sprint name.
            ticket_type: Filter by story/bug/task.
            priority: Filter by priority level.
            role: Filter by author role.
            page: 1-based page number.
            page_size: Maximum results per page.

        Returns:
            tuple[list[Ticket], int]: Tickets for the current page and total count.
        """
        with self.db.session() as session:
            query = select(Ticket)
            if status:
                query = query.where(Ticket.status == status)
            if assignee:
                query = query.where(Ticket.assignee == assignee)
            if sprint:
                query = query.where(Ticket.sprint == sprint)
            if project:
                query = query.where(Ticket.project == project)
            if ticket_type:
                query = query.where(Ticket.ticket_type == ticket_type)
            if priority:
                query = query.where(Ticket.priority == priority)
            if role:
                query = query.where(Ticket.role == role)

            count_q = select(func.count()).select_from(query.subquery())
            total = session.execute(count_q).scalar() or 0

            query = query.order_by(Ticket.created_at.desc())
            query = query.offset((page - 1) * page_size).limit(page_size)
            tickets = list(session.execute(query).scalars())
            return tickets, total

    def search(self, query: str, page: int = 1, page_size: int = 20) -> tuple[list[Ticket], int]:
        pattern = f"%{query}%"
        with self.db.session() as session:
            stmt = select(Ticket).where(
                or_(
                    Ticket.key.like(pattern),
                    Ticket.title.like(pattern),
                    Ticket.description.like(pattern),
                    Ticket.assignee.like(pattern),
                )
            )
            count_q = select(func.count()).select_from(stmt.subquery())
            total = session.execute(count_q).scalar() or 0
            stmt = stmt.order_by(Ticket.created_at.desc())
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)
            tickets = list(session.execute(stmt).scalars())
            return tickets, total

    def board_data(
        self,
        sprint: Optional[str] = None,
        project: Optional[str] = None,
        per_column_limit: int = 100,
    ) -> dict[str, list[Ticket]]:
        """Return tickets grouped by status for the board view.

        Runs one query per status column so each query can use the status
        index and apply a LIMIT, avoiding a full table scan.

        Args:
            sprint: Optionally restrict to a single sprint.
            project: Optionally restrict to a single project.
            per_column_limit: Max tickets returned per column (default 100).

        Returns:
            dict[str, list[Ticket]]: Status -> list of tickets mapping.
        """
        priority_order = case(
            (Ticket.priority == Priority.CRITICAL, 0),
            (Ticket.priority == Priority.HIGH, 1),
            (Ticket.priority == Priority.MEDIUM, 2),
            (Ticket.priority == Priority.LOW, 3),
            else_=4,
        )
        board: dict[str, list[Ticket]] = {
            TicketStatus.BACKLOG: [],
            TicketStatus.IN_PROGRESS: [],
            TicketStatus.REVIEW: [],
            TicketStatus.DONE: [],
        }
        with self.db.session() as session:
            for status in board:
                q = select(Ticket).where(Ticket.status == status)
                if sprint:
                    q = q.where(Ticket.sprint == sprint)
                if project:
                    q = q.where(Ticket.project == project)
                q = q.order_by(priority_order, Ticket.created_at).limit(per_column_limit)
                board[status] = list(session.execute(q).scalars())
        return board

    def count_by_status(self) -> dict[str, int]:
        """Return ticket counts grouped by status using a single aggregate query.

        Returns:
            dict[str, int]: Status -> count mapping.
        """
        with self.db.session() as session:
            rows = session.execute(
                select(Ticket.status, func.count().label("n")).group_by(Ticket.status)
            ).all()
        return {row.status: row.n for row in rows}

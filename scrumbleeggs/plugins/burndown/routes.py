"""API routes for the Burndown plugin."""
from __future__ import annotations

from datetime import date as date_type, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

router = APIRouter()
_db = None  # injected via configure()


def configure(db) -> None:
    global _db
    _db = db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_snapshot(session, sprint, tickets) -> None:
    """Upsert today's snapshot for a sprint (idempotent)."""
    from .models import BurndownSnapshot

    today = date_type.today()
    total_pts = sum(t.story_points or 0 for t in tickets)
    done_pts = sum(t.story_points or 0 for t in tickets if t.status == "done")
    total_t = len(tickets)
    done_t = sum(1 for t in tickets if t.status == "done")

    existing = session.execute(
        select(BurndownSnapshot).where(
            BurndownSnapshot.sprint_id == sprint.id,
            BurndownSnapshot.snapshot_date == today,
        )
    ).scalar_one_or_none()

    if existing:
        existing.remaining_points = total_pts - done_pts
        existing.remaining_tickets = total_t - done_t
        existing.total_points = total_pts
        existing.total_tickets = total_t
    else:
        session.add(BurndownSnapshot(
            sprint_id=sprint.id,
            sprint_name=sprint.name,
            snapshot_date=today,
            remaining_points=total_pts - done_pts,
            remaining_tickets=total_t - done_t,
            total_points=total_pts,
            total_tickets=total_t,
        ))


def _build_ideal_line(start: date_type, end: date_type, total: float) -> list[dict]:
    days_total = max((end - start).days, 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "value": round(total * (1 - i / days_total), 2)}
        for i in range(days_total + 1)
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/sprints")
async def list_sprints():
    """Return all sprints (id, name, status, start/end dates)."""
    from ...db import Sprint
    with _db.session() as session:
        sprints = list(session.execute(select(Sprint).order_by(Sprint.id.desc())).scalars())
        return [s.to_dict() for s in sprints]


@router.get("/sprints/{sprint_id}/burndown")
async def get_burndown(sprint_id: int):
    """Return burndown chart data, recording today's snapshot automatically."""
    from ...db import Sprint, Ticket
    from .models import BurndownSnapshot

    with _db.session() as session:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        tickets = list(
            session.execute(select(Ticket).where(Ticket.sprint == sprint.name)).scalars()
        )

        _record_snapshot(session, sprint, tickets)
        session.flush()

        snapshots = list(
            session.execute(
                select(BurndownSnapshot)
                .where(BurndownSnapshot.sprint_id == sprint_id)
                .order_by(BurndownSnapshot.snapshot_date)
            ).scalars()
        )

        today = date_type.today()
        start = sprint.start_date or today
        if hasattr(start, "date"):
            start = start.date()
        end = sprint.end_date or today
        if hasattr(end, "date"):
            end = end.date()

        total_pts = sum(t.story_points or 0 for t in tickets)
        total_t = len(tickets)

        return {
            "sprint_id": sprint_id,
            "sprint_name": sprint.name,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_points": total_pts,
            "total_tickets": total_t,
            "ideal_points": _build_ideal_line(start, end, total_pts),
            "ideal_tickets": _build_ideal_line(start, end, total_t),
            "snapshots": [s.to_dict() for s in snapshots],
        }

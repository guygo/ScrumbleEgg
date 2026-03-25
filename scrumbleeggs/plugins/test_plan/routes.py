"""FastAPI routes for the Test Planning plugin."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(tags=["test_plan"])

# Injected by configure() — avoids circular imports with app.py
_db = None


def configure(db) -> None:
    """Receive the Database instance from the plugin loader."""
    global _db
    _db = db


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class PlanCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sprint: Optional[str] = None
    status: str = "draft"


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sprint: Optional[str] = None
    status: Optional[str] = None


class CaseCreate(BaseModel):
    title: str
    steps: Optional[str] = None
    expected: Optional[str] = None
    ticket_key: Optional[str] = None


class CaseUpdate(BaseModel):
    title: Optional[str] = None
    steps: Optional[str] = None
    expected: Optional[str] = None
    ticket_key: Optional[str] = None
    result: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Test Plan CRUD
# ---------------------------------------------------------------------------


@router.get("/plans")
def list_plans():
    """Return all test plans ordered by newest first."""
    from .models import TestPlan
    with _db.session() as sess:
        plans = sess.execute(
            select(TestPlan).order_by(TestPlan.id.desc())
        ).scalars().all()
        return [p.to_dict() for p in plans]


@router.post("/plans", status_code=201)
def create_plan(body: PlanCreate):
    """Create a new test plan."""
    from .models import TestPlan
    valid_statuses = {"draft", "active", "closed"}
    if body.status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"status must be one of {valid_statuses}")
    with _db.session() as sess:
        plan = TestPlan(
            name=body.name.strip(),
            description=body.description,
            sprint=body.sprint,
            status=body.status,
        )
        sess.add(plan)
        sess.flush()
        return plan.to_dict()


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int):
    """Return a single test plan."""
    from .models import TestPlan
    with _db.session() as sess:
        plan = sess.get(TestPlan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Test plan not found")
        return plan.to_dict()


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanUpdate):
    """Update a test plan's fields."""
    from .models import TestPlan
    valid_statuses = {"draft", "active", "closed"}
    with _db.session() as sess:
        plan = sess.get(TestPlan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Test plan not found")
        if body.name is not None:
            plan.name = body.name.strip()
        if body.description is not None:
            plan.description = body.description
        if body.sprint is not None:
            plan.sprint = body.sprint
        if body.status is not None:
            if body.status not in valid_statuses:
                raise HTTPException(status_code=422, detail=f"status must be one of {valid_statuses}")
            plan.status = body.status
        return plan.to_dict()


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int):
    """Delete a test plan and all its cases (cascade)."""
    from .models import TestPlan, TestCase
    with _db.session() as sess:
        plan = sess.get(TestPlan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Test plan not found")
        # Delete cases first (SQLite may not enforce FK cascade)
        cases = sess.execute(
            select(TestCase).where(TestCase.plan_id == plan_id)
        ).scalars().all()
        for c in cases:
            sess.delete(c)
        sess.delete(plan)


# ---------------------------------------------------------------------------
# Test Case CRUD
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}/cases")
def list_cases(plan_id: int):
    """Return all test cases for a plan, ordered by creation."""
    from .models import TestCase
    with _db.session() as sess:
        cases = sess.execute(
            select(TestCase)
            .where(TestCase.plan_id == plan_id)
            .order_by(TestCase.id.asc())
        ).scalars().all()
        return [c.to_dict() for c in cases]


@router.post("/plans/{plan_id}/cases", status_code=201)
def create_case(plan_id: int, body: CaseCreate):
    """Add a test case to a plan."""
    from .models import TestPlan, TestCase
    with _db.session() as sess:
        plan = sess.get(TestPlan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Test plan not found")
        case = TestCase(
            plan_id=plan_id,
            title=body.title.strip(),
            steps=body.steps,
            expected=body.expected,
            ticket_key=body.ticket_key.strip().upper() if body.ticket_key else None,
        )
        sess.add(case)
        sess.flush()
        return case.to_dict()


@router.patch("/plans/{plan_id}/cases/{case_id}")
def update_case(plan_id: int, case_id: int, body: CaseUpdate):
    """Update a test case (result, title, notes, etc.)."""
    from .models import TestCase
    valid_results = {"pending", "pass", "fail", "blocked"}
    with _db.session() as sess:
        case = sess.get(TestCase, case_id)
        if not case or case.plan_id != plan_id:
            raise HTTPException(status_code=404, detail="Test case not found")
        if body.title is not None:
            case.title = body.title.strip()
        if body.steps is not None:
            case.steps = body.steps
        if body.expected is not None:
            case.expected = body.expected
        if body.ticket_key is not None:
            case.ticket_key = body.ticket_key.strip().upper() or None
        if body.result is not None:
            if body.result not in valid_results:
                raise HTTPException(status_code=422, detail=f"result must be one of {valid_results}")
            case.result = body.result
        if body.notes is not None:
            case.notes = body.notes
        return case.to_dict()


@router.delete("/plans/{plan_id}/cases/{case_id}", status_code=204)
def delete_case(plan_id: int, case_id: int):
    """Delete a single test case."""
    from .models import TestCase
    with _db.session() as sess:
        case = sess.get(TestCase, case_id)
        if not case or case.plan_id != plan_id:
            raise HTTPException(status_code=404, detail="Test case not found")
        sess.delete(case)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}/stats")
def plan_stats(plan_id: int):
    """Return pass/fail/blocked/pending counts for a plan."""
    from .models import TestCase
    with _db.session() as sess:
        cases = sess.execute(
            select(TestCase).where(TestCase.plan_id == plan_id)
        ).scalars().all()
        total = len(cases)
        counts = {"pending": 0, "pass": 0, "fail": 0, "blocked": 0}
        for c in cases:
            counts[c.result] = counts.get(c.result, 0) + 1
        pct = round(counts["pass"] / total * 100) if total else 0
        return {"total": total, **counts, "pass_pct": pct}

"""
Initiatives router — the core Founder OS entity.

Phase 2 additions:
  - visibility field: private | team | public
  - Role-aware read: founder sees all; coo sees team+public; staff sees assigned+public; viewer sees public
  - Role-aware write: founder + coo can create/update; staff/viewer get 403

CRUD for initiatives + score management.
Every initiative tracks Build / Distribution / Revenue scores.
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import gateway_auth
import workspace_auth
import models
from database import get_db
from .events import emit_event

log = logging.getLogger("mytodo.initiatives")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_STAGES      = {"ideation", "building", "launched", "distributing", "revenue", "paused"}
VALID_CATEGORIES  = {"product", "infra", "platform", "content", "personal"}
VALID_VISIBILITY  = {"private", "team", "public"}

_coo_or_above  = workspace_auth.require_role("founder", "coo")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid  = identity["uid"]
    role = identity["role"]

    initiatives = _query_initiatives(db, identity).order_by(
        models.Initiative.updated_at.desc()
    ).all()

    # Today's tasks — role-aware
    today = date.today()
    if role == "founder":
        today_tasks = (
            db.query(models.Task)
            .filter(
                models.Task.gateway_user_id == 1,  # all founder tasks
                models.Task.for_date == today,
                models.Task.status.in_(["open", "in_progress"]),
            )
        )
    elif role == "coo":
        today_tasks = (
            db.query(models.Task)
            .filter(
                models.Task.for_date == today,
                models.Task.status.in_(["open", "in_progress"]),
            )
        )
    else:
        today_tasks = (
            db.query(models.Task)
            .filter(
                models.Task.assigned_to_user_id == uid,
                models.Task.for_date == today,
                models.Task.status.in_(["open", "in_progress"]),
            )
        )
    today_tasks = today_tasks.order_by(
        models.Task.priority.desc(), models.Task.created_at.asc()
    ).all()

    # Latest PHANT brief (founder only — contains revenue/ecosystem data)
    brief = None
    if role == "founder":
        brief = (
            db.query(models.DailyBrief)
            .filter_by(gateway_user_id=1)
            .order_by(models.DailyBrief.brief_date.desc())
            .first()
        )

    # Distribution queue
    if role in ("founder", "coo"):
        pending_distribution = (
            db.query(models.DistributionAction)
            .filter_by(gateway_user_id=1, status="pending")
            .order_by(models.DistributionAction.created_at.desc())
            .limit(5)
            .all()
        )
    else:
        pending_distribution = []

    # Revenue totals (founder only)
    total_revenue = 0.0
    if role == "founder":
        total_revenue = sum(i.revenue_total or 0 for i in initiatives)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": identity,
        "initiatives": initiatives,
        "today_tasks": today_tasks,
        "today": today,
        "brief": brief,
        "pending_distribution": pending_distribution,
        "total_revenue": total_revenue,
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.get("/initiatives/new", response_class=HTMLResponse)
async def new_initiative_page(
    request: Request,
    identity: dict = Depends(_coo_or_above),
):
    return templates.TemplateResponse("new_initiative.html", {
        "request": request,
        "user": identity,
        "stages": list(VALID_STAGES),
        "categories": list(VALID_CATEGORIES),
        "visibility_options": list(VALID_VISIBILITY),
    })


@router.post("/initiatives")
async def create_initiative(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default="product"),
    stage: str = Form(default="building"),
    visibility: str = Form(default="private"),
    build_score: int = Form(default=0),
    distribution_score: int = Form(default=0),
    build_notes: str = Form(default=""),
    distribution_notes: str = Form(default=""),
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    uid = identity["uid"]
    initiative = models.Initiative(
        gateway_user_id=1,           # always owned by founder; COO creates on behalf
        name=name.strip(),
        description=description.strip(),
        category=category if category in VALID_CATEGORIES else "product",
        stage=stage if stage in VALID_STAGES else "building",
        visibility=visibility if visibility in VALID_VISIBILITY else "private",
        build_score=max(0, min(100, build_score)),
        distribution_score=max(0, min(100, distribution_score)),
        build_notes=build_notes.strip(),
        distribution_notes=distribution_notes.strip(),
    )
    initiative.bottleneck = initiative.compute_bottleneck()
    db.add(initiative)
    db.commit()
    db.refresh(initiative)

    await emit_event("MYTODO_GOAL_CREATED", {
        "initiative_id": initiative.id,
        "name": initiative.name,
        "stage": initiative.stage,
        "created_by": identity["email"],
        "user_id": uid,
    })

    return RedirectResponse(f"/initiatives/{initiative.id}", status_code=303)


# ── Read ──────────────────────────────────────────────────────────────────────

@router.get("/initiatives/{initiative_id}", response_class=HTMLResponse)
async def initiative_detail(
    request: Request,
    initiative_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative_for_read(db, initiative_id, identity)
    role = identity["role"]
    uid  = identity["uid"]

    today = date.today()
    open_tasks  = [t for t in initiative.tasks if t.status in ("open", "in_progress")]
    done_tasks  = [t for t in initiative.tasks if t.status == "done"]
    pending_dist   = [d for d in initiative.distribution_actions if d.status == "pending"]
    completed_dist = [d for d in initiative.distribution_actions if d.status == "completed"]

    # Staff sees only their assigned tasks
    if role == "staff":
        open_tasks = [t for t in open_tasks if t.assigned_to_user_id == uid]
        done_tasks = [t for t in done_tasks if t.assigned_to_user_id == uid]
        pending_dist   = []
        completed_dist = []

    # COO / viewer can't see revenue data on initiative
    show_revenue = (role == "founder")

    return templates.TemplateResponse("initiative.html", {
        "request": request,
        "user": identity,
        "initiative": initiative,
        "open_tasks": sorted(open_tasks, key=lambda t: _priority_rank(t.priority)),
        "done_tasks": sorted(done_tasks, key=lambda t: t.done_at or datetime.utcnow(), reverse=True)[:10],
        "pending_dist": pending_dist,
        "completed_dist": completed_dist[:10],
        "today": today,
        "can_edit": role in ("founder", "coo"),
        "show_revenue": show_revenue,
    })


# ── Update ────────────────────────────────────────────────────────────────────

@router.post("/initiatives/{initiative_id}/update")
async def update_initiative(
    request: Request,
    initiative_id: int,
    name: str = Form(...),
    description: str = Form(default=""),
    stage: str = Form(default="building"),
    visibility: str = Form(default="private"),
    build_score: int = Form(default=0),
    distribution_score: int = Form(default=0),
    revenue_score: int = Form(default=0),
    build_notes: str = Form(default=""),
    distribution_notes: str = Form(default=""),
    revenue_notes: str = Form(default=""),
    users_count: int = Form(default=0),
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative_for_write(db, initiative_id, identity)

    initiative.name = name.strip()
    initiative.description = description.strip()
    initiative.stage = stage if stage in VALID_STAGES else initiative.stage
    initiative.visibility = visibility if visibility in VALID_VISIBILITY else initiative.visibility
    initiative.build_score = max(0, min(100, build_score))
    initiative.distribution_score = max(0, min(100, distribution_score))

    # Only founder can set revenue score/notes
    if identity["role"] == "founder":
        initiative.revenue_score = max(0, min(100, revenue_score))
        initiative.revenue_notes = revenue_notes.strip()

    initiative.build_notes = build_notes.strip()
    initiative.distribution_notes = distribution_notes.strip()
    initiative.users_count = max(0, users_count)
    initiative.bottleneck = initiative.compute_bottleneck()
    initiative.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(f"/initiatives/{initiative_id}", status_code=303)


@router.post("/initiatives/{initiative_id}/pause")
async def pause_initiative(
    initiative_id: int,
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative_for_write(db, initiative_id, identity)
    initiative.stage = "paused"
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/initiatives/{initiative_id}/archive")
async def archive_initiative(
    initiative_id: int,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative_for_write(db, initiative_id, identity)
    initiative.is_active = False
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _query_initiatives(db: Session, identity: dict):
    """Return a SQLAlchemy query filtered by the user's role + visibility."""
    role = identity["role"]
    uid  = identity["uid"]
    base = db.query(models.Initiative).filter_by(is_active=True)

    if role == "founder":
        return base

    if role == "coo":
        return base.filter(
            models.Initiative.visibility.in_(["team", "public"])
        )

    if role == "staff":
        assigned_ids = (
            db.query(models.Task.initiative_id)
            .filter(models.Task.assigned_to_user_id == uid)
            .filter(models.Task.initiative_id.isnot(None))
            .distinct()
        )
        return base.filter(
            (models.Initiative.visibility == "public") |
            (models.Initiative.id.in_(assigned_ids))
        )

    # viewer
    return base.filter(models.Initiative.visibility == "public")


def _get_initiative_for_read(db: Session, initiative_id: int, identity: dict) -> models.Initiative:
    """Load initiative with visibility access check."""
    role = identity["role"]
    uid  = identity["uid"]

    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, is_active=True
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")

    if role == "founder":
        return initiative

    if role == "coo" and initiative.visibility in ("team", "public"):
        return initiative

    if role == "staff":
        if initiative.visibility == "public":
            return initiative
        has_task = db.query(models.Task).filter_by(
            initiative_id=initiative_id, assigned_to_user_id=uid
        ).first()
        if has_task:
            return initiative

    if role == "viewer" and initiative.visibility == "public":
        return initiative

    raise HTTPException(status_code=403, detail="Access denied")


def _get_initiative_for_write(db: Session, initiative_id: int, identity: dict) -> models.Initiative:
    """Load initiative with write access check (founder or coo)."""
    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, is_active=True
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return initiative


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)

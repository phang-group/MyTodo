"""
Initiatives router — the core Founder OS entity.

CRUD for initiatives + score management.
Every initiative tracks Build / Distribution / Revenue scores.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import gateway_auth
import models
from database import get_db
from .events import emit_event

log = logging.getLogger("mytodo.initiatives")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_STAGES = {"ideation", "building", "launched", "distributing", "revenue", "paused"}
VALID_CATEGORIES = {"product", "infra", "platform", "content", "personal"}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=uid, is_active=True)
        .order_by(models.Initiative.updated_at.desc())
        .all()
    )

    # Today's open tasks across all initiatives
    from datetime import date
    today = date.today()
    today_tasks = (
        db.query(models.Task)
        .filter(
            models.Task.gateway_user_id == uid,
            models.Task.for_date == today,
            models.Task.status.in_(["open", "in_progress"]),
        )
        .order_by(
            models.Task.priority.desc(),
            models.Task.created_at.asc(),
        )
        .all()
    )

    # Latest PHANT brief
    brief = (
        db.query(models.DailyBrief)
        .filter_by(gateway_user_id=uid)
        .order_by(models.DailyBrief.brief_date.desc())
        .first()
    )

    # Distribution queue — pending AI-suggested actions
    pending_distribution = (
        db.query(models.DistributionAction)
        .filter_by(gateway_user_id=uid, status="pending")
        .order_by(models.DistributionAction.created_at.desc())
        .limit(5)
        .all()
    )

    # Revenue totals
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
    identity: dict = Depends(gateway_auth.require_identity),
):
    return templates.TemplateResponse("new_initiative.html", {
        "request": request,
        "user": identity,
        "stages": list(VALID_STAGES),
        "categories": list(VALID_CATEGORIES),
    })


@router.post("/initiatives")
async def create_initiative(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default="product"),
    stage: str = Form(default="building"),
    build_score: int = Form(default=0),
    distribution_score: int = Form(default=0),
    build_notes: str = Form(default=""),
    distribution_notes: str = Form(default=""),
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    initiative = models.Initiative(
        gateway_user_id=uid,
        name=name.strip(),
        description=description.strip(),
        category=category if category in VALID_CATEGORIES else "product",
        stage=stage if stage in VALID_STAGES else "building",
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
    uid = identity["user_id"]
    initiative = _get_initiative(db, initiative_id, uid)

    from datetime import date
    today = date.today()
    open_tasks = [t for t in initiative.tasks if t.status in ("open", "in_progress")]
    done_tasks = [t for t in initiative.tasks if t.status == "done"]
    pending_dist = [d for d in initiative.distribution_actions if d.status == "pending"]
    completed_dist = [d for d in initiative.distribution_actions if d.status == "completed"]

    return templates.TemplateResponse("initiative.html", {
        "request": request,
        "user": identity,
        "initiative": initiative,
        "open_tasks": sorted(open_tasks, key=lambda t: _priority_rank(t.priority)),
        "done_tasks": sorted(done_tasks, key=lambda t: t.done_at or datetime.utcnow(), reverse=True)[:10],
        "pending_dist": pending_dist,
        "completed_dist": completed_dist[:10],
        "today": today,
    })


# ── Update ────────────────────────────────────────────────────────────────────

@router.post("/initiatives/{initiative_id}/update")
async def update_initiative(
    request: Request,
    initiative_id: int,
    name: str = Form(...),
    description: str = Form(default=""),
    stage: str = Form(default="building"),
    build_score: int = Form(default=0),
    distribution_score: int = Form(default=0),
    revenue_score: int = Form(default=0),
    build_notes: str = Form(default=""),
    distribution_notes: str = Form(default=""),
    revenue_notes: str = Form(default=""),
    users_count: int = Form(default=0),
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    initiative = _get_initiative(db, initiative_id, uid)

    initiative.name = name.strip()
    initiative.description = description.strip()
    initiative.stage = stage if stage in VALID_STAGES else initiative.stage
    initiative.build_score = max(0, min(100, build_score))
    initiative.distribution_score = max(0, min(100, distribution_score))
    initiative.revenue_score = max(0, min(100, revenue_score))
    initiative.build_notes = build_notes.strip()
    initiative.distribution_notes = distribution_notes.strip()
    initiative.revenue_notes = revenue_notes.strip()
    initiative.users_count = max(0, users_count)
    initiative.bottleneck = initiative.compute_bottleneck()
    initiative.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(f"/initiatives/{initiative_id}", status_code=303)


@router.post("/initiatives/{initiative_id}/pause")
async def pause_initiative(
    initiative_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    initiative = _get_initiative(db, initiative_id, uid)
    initiative.stage = "paused"
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/initiatives/{initiative_id}/archive")
async def archive_initiative(
    initiative_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    initiative = _get_initiative(db, initiative_id, uid)
    initiative.is_active = False
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_initiative(db: Session, initiative_id: int, uid: int) -> models.Initiative:
    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, gateway_user_id=uid
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return initiative


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)

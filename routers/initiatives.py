"""
Initiatives router — the core Founder OS entity.

OWNERSHIP MODEL (Phase 2):
  gateway_user_id = the user who owns this initiative.
  visibility = who else can see it:
    private  → owner only
    team     → all approved workspace members
    public   → all approved workspace members (same as team; rarely used)

ACCESS RULES:
  Create/update: any approved user (Viewer is read-only).
  Read:   founder sees ALL; others see own + team/public.
  Archive: owner only (or founder override).

Roles control AUTHORITY (invite, approve), not feature access.
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_

import gateway_auth
import workspace_auth
import models
from database import get_db
from .events import emit_event

log = logging.getLogger("mytodo.initiatives")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_STAGES     = {"ideation", "building", "launched", "distributing", "revenue", "paused"}
VALID_CATEGORIES = {"product", "infra", "platform", "content", "personal"}
VALID_VISIBILITY = {"private", "team", "public"}

# Viewer is read-only — all other roles can create/update
_not_viewer = workspace_auth.require_role("founder", "coo", "staff")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid  = identity["uid"]
    role = identity["role"]

    initiatives = _visible_initiatives(db, identity).order_by(
        models.Initiative.updated_at.desc()
    ).all()

    # Today's open tasks — visible to this user
    today = date.today()
    tasks_q = db.query(models.Task).filter(
        models.Task.for_date == today,
        models.Task.status.in_(["open", "in_progress"]),
    )
    today_tasks = _visible_query(tasks_q, models.Task, identity).order_by(
        models.Task.priority.desc(), models.Task.created_at.asc()
    ).all()

    # Latest brief for this user
    brief = (
        db.query(models.DailyBrief)
        .filter_by(gateway_user_id=uid)
        .order_by(models.DailyBrief.brief_date.desc())
        .first()
    )

    # Pending distribution visible to this user
    dist_q = db.query(models.DistributionAction).filter_by(status="pending")
    pending_distribution = _visible_query(dist_q, models.DistributionAction, identity) \
        .order_by(models.DistributionAction.created_at.desc()) \
        .limit(5).all()

    # Revenue totals: sum of what's visible to this user
    rev_q = db.query(models.RevenueRecord)
    visible_revenue = _visible_query(rev_q, models.RevenueRecord, identity).all()
    total_revenue = sum(r.amount for r in visible_revenue)

    return templates.TemplateResponse("dashboard.html", {
        "request":             request,
        "user":                identity,
        "initiatives":         initiatives,
        "today_tasks":         today_tasks,
        "today":               today,
        "brief":               brief,
        "pending_distribution": pending_distribution,
        "total_revenue":       total_revenue,
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.get("/initiatives/new", response_class=HTMLResponse)
async def new_initiative_page(
    request: Request,
    identity: dict = Depends(_not_viewer),
):
    return templates.TemplateResponse("new_initiative.html", {
        "request": request,
        "user":    identity,
        "stages":            list(VALID_STAGES),
        "categories":        list(VALID_CATEGORIES),
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
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    uid = identity["uid"]
    initiative = models.Initiative(
        gateway_user_id=uid,      # owned by the creating user
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
        "name":          initiative.name,
        "stage":         initiative.stage,
        "created_by":    identity["email"],
        "user_id":       uid,
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
    initiative = _get_initiative(db, initiative_id, identity)
    uid  = identity["uid"]
    role = identity["role"]

    today = date.today()

    # Tasks: show visible ones
    all_tasks  = initiative.tasks
    open_tasks = [t for t in all_tasks if t.status in ("open", "in_progress") and _is_visible(t, identity)]
    done_tasks = [t for t in all_tasks if t.status == "done" and _is_visible(t, identity)]

    # Distribution: show visible ones
    all_dist       = initiative.distribution_actions
    pending_dist   = [d for d in all_dist if d.status == "pending"   and _is_visible(d, identity)]
    completed_dist = [d for d in all_dist if d.status == "completed" and _is_visible(d, identity)]

    # Revenue: visible records only
    all_rev        = initiative.revenue_records
    visible_rev    = [r for r in all_rev if _is_visible(r, identity)]
    can_edit       = role != "viewer"
    is_owner       = (initiative.gateway_user_id == uid) or role == "founder"

    return templates.TemplateResponse("initiative.html", {
        "request":        request,
        "user":           identity,
        "initiative":     initiative,
        "open_tasks":     sorted(open_tasks, key=lambda t: _priority_rank(t.priority)),
        "done_tasks":     sorted(done_tasks, key=lambda t: t.done_at or datetime.utcnow(), reverse=True)[:10],
        "pending_dist":   pending_dist,
        "completed_dist": completed_dist[:10],
        "visible_rev":    visible_rev[:10],
        "today":          today,
        "can_edit":       can_edit,
        "is_owner":       is_owner,
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
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative(db, initiative_id, identity, require_edit=True)

    initiative.name             = name.strip()
    initiative.description      = description.strip()
    initiative.stage            = stage if stage in VALID_STAGES else initiative.stage
    initiative.visibility       = visibility if visibility in VALID_VISIBILITY else initiative.visibility
    initiative.build_score      = max(0, min(100, build_score))
    initiative.distribution_score = max(0, min(100, distribution_score))
    initiative.build_notes      = build_notes.strip()
    initiative.distribution_notes = distribution_notes.strip()
    initiative.users_count      = max(0, users_count)

    # Revenue score/notes: only if user can see revenue on this initiative
    uid = identity["uid"]
    if initiative.gateway_user_id == uid or identity["role"] == "founder":
        initiative.revenue_score = max(0, min(100, revenue_score))
        initiative.revenue_notes = revenue_notes.strip()

    initiative.bottleneck = initiative.compute_bottleneck()
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/initiatives/{initiative_id}", status_code=303)


@router.post("/initiatives/{initiative_id}/pause")
async def pause_initiative(
    initiative_id: int,
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative(db, initiative_id, identity, require_edit=True)
    initiative.stage      = "paused"
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/initiatives/{initiative_id}/archive")
async def archive_initiative(
    initiative_id: int,
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    initiative = _get_initiative(db, initiative_id, identity, require_edit=True)
    initiative.is_active  = False
    initiative.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/", status_code=303)


# ── Visibility helpers ────────────────────────────────────────────────────────

def _visible_query(query, model_class, identity):
    """
    Narrow a SQLAlchemy query to objects visible to the current user.
    Founder sees everything. Others see: (owned by them) OR (team/public visibility).
    """
    uid  = identity["uid"]
    role = identity["role"]
    if role == "founder":
        return query
    return query.filter(
        or_(
            model_class.gateway_user_id == uid,
            model_class.visibility.in_(["team", "public"]),
        )
    )


def _visible_initiatives(db: Session, identity: dict):
    """Return a query for initiatives visible to the user."""
    return _visible_query(
        db.query(models.Initiative).filter_by(is_active=True),
        models.Initiative,
        identity,
    )


def _is_visible(obj, identity: dict) -> bool:
    """Check if a single ORM object is visible to the user (used for in-memory filtering)."""
    role = identity["role"]
    uid  = identity["uid"]
    if role == "founder":
        return True
    if getattr(obj, "gateway_user_id", None) == uid:
        return True
    v = getattr(obj, "visibility", "team")
    return v in ("team", "public")


def _get_initiative(
    db: Session, initiative_id: int, identity: dict, require_edit: bool = False
) -> models.Initiative:
    """
    Load initiative with visibility check.
    require_edit=True: user must be owner or founder to modify.
    """
    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, is_active=True
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")

    # Visibility check for reading
    if not _is_visible(initiative, identity):
        raise HTTPException(status_code=403, detail="Access denied")

    # Edit check: owner or founder
    if require_edit:
        uid  = identity["uid"]
        role = identity["role"]
        if initiative.gateway_user_id != uid and role != "founder":
            raise HTTPException(status_code=403, detail="Only the owner or founder can modify this")

    return initiative


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)

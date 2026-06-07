"""
Distribution router — closing the Build/Distribution gap.

When code ships, PHANT suggests distribution actions.
Any workspace member marks them done. Distribution Score increases.

OWNERSHIP MODEL (Phase 2):
  gateway_user_id = the user who created this distribution action.
  visibility controls who sees it:
    team    → all approved workspace members (default — campaigns are shared)
    private → owner only
    public  → all

ACCESS RULES:
  Create:         any approved user except Viewer
  View queue:     visibility-based (team = all see pending)
  Complete/skip:  owner or founder (can't complete someone else's action)
"""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

import gateway_auth
import workspace_auth
import models
from database import get_db
from .events import emit_event

log = logging.getLogger("mytodo.distribution")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# All approved users except Viewer can create and act on distribution
_not_viewer = workspace_auth.require_role("founder", "coo", "staff")

CHANNELS = [
    "x_post", "reddit", "youtube", "devlog",
    "whatsapp_broadcast", "linkedin", "producthunt",
    "newsletter", "other",
]


def _visible_q(q, identity):
    """Filter a DistributionAction query by visibility for the current user."""
    uid, role = identity["uid"], identity["role"]
    if role == "founder":
        return q
    return q.filter(or_(
        models.DistributionAction.gateway_user_id == uid,
        models.DistributionAction.visibility.in_(["team", "public"]),
    ))


def _visible_initiatives(db: Session, identity: dict):
    uid, role = identity["uid"], identity["role"]
    q = db.query(models.Initiative).filter_by(is_active=True)
    if role == "founder":
        return q
    return q.filter(or_(
        models.Initiative.gateway_user_id == uid,
        models.Initiative.visibility.in_(["team", "public"]),
    ))


@router.get("/distribution", response_class=HTMLResponse)
async def distribution_queue(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    pending = (
        _visible_q(
            db.query(models.DistributionAction).filter_by(status="pending"),
            identity,
        )
        .order_by(models.DistributionAction.ai_suggested.desc(), models.DistributionAction.created_at.asc())
        .all()
    )
    completed = (
        _visible_q(
            db.query(models.DistributionAction).filter_by(status="completed"),
            identity,
        )
        .order_by(models.DistributionAction.completed_at.desc())
        .limit(20)
        .all()
    )
    initiatives = (
        _visible_initiatives(db, identity)
        .order_by(models.Initiative.name.asc())
        .all()
    )
    return templates.TemplateResponse("distribution.html", {
        "request":    request,
        "user":       identity,
        "pending":    pending,
        "completed":  completed,
        "initiatives": initiatives,
        "channels":   CHANNELS,
        "can_create": identity["role"] != "viewer",
    })


@router.post("/distribution")
async def create_distribution_action(
    initiative_id: int = Form(default=None),
    channel: str = Form(...),
    description: str = Form(...),
    visibility: str = Form(default="team"),
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    uid = identity["uid"]
    action = models.DistributionAction(
        gateway_user_id=uid,
        initiative_id=initiative_id or None,
        channel=channel if channel in CHANNELS else "other",
        description=description.strip(),
        visibility=visibility if visibility in ("private", "team", "public") else "team",
        ai_suggested=False,
    )
    db.add(action)
    db.commit()
    return RedirectResponse("/distribution", status_code=303)


@router.post("/distribution/{action_id}/complete")
async def complete_action(
    action_id: int,
    impact_notes: str = Form(default=""),
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    action = _get_action_for_write(db, action_id, identity)
    action.status       = "completed"
    action.impact_notes = impact_notes.strip()
    action.completed_at = datetime.utcnow()
    db.commit()

    await emit_event("MYTODO_DISTRIBUTION_COMPLETED", {
        "action_id":    action.id,
        "channel":      action.channel,
        "initiative_id": action.initiative_id,
        "user_id":      identity["uid"],
    })

    return RedirectResponse("/distribution", status_code=303)


@router.post("/distribution/{action_id}/skip")
async def skip_action(
    action_id: int,
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    action = _get_action_for_write(db, action_id, identity)
    action.status = "skipped"
    db.commit()
    return RedirectResponse("/distribution", status_code=303)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_action_for_write(
    db: Session, action_id: int, identity: dict
) -> models.DistributionAction:
    """
    Load action for a mutating operation (complete/skip).
    Founder can act on any action.
    Others can only act on their own actions.
    """
    action = db.query(models.DistributionAction).filter_by(id=action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Distribution action not found")

    uid  = identity["uid"]
    role = identity["role"]

    if role == "founder":
        return action

    if action.gateway_user_id != uid:
        raise HTTPException(
            status_code=403,
            detail="Only the action owner can complete or skip it",
        )
    return action

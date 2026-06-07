"""
Distribution router — closing the Build/Distribution gap.

When code ships, PHANT suggests distribution actions.
The founder marks them done. Distribution Score increases.
"""

import logging
from datetime import datetime
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

_coo_or_above = workspace_auth.require_role("founder", "coo")

log = logging.getLogger("mytodo.distribution")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

CHANNELS = [
    "x_post", "reddit", "youtube", "devlog",
    "whatsapp_broadcast", "linkedin", "producthunt",
    "newsletter", "other",
]


@router.get("/distribution", response_class=HTMLResponse)
async def distribution_queue(
    request: Request,
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    pending = (
        db.query(models.DistributionAction)
        .filter_by(gateway_user_id=uid, status="pending")
        .order_by(models.DistributionAction.ai_suggested.desc(), models.DistributionAction.created_at.asc())
        .all()
    )
    completed = (
        db.query(models.DistributionAction)
        .filter_by(gateway_user_id=uid, status="completed")
        .order_by(models.DistributionAction.completed_at.desc())
        .limit(20)
        .all()
    )
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=uid, is_active=True)
        .order_by(models.Initiative.name.asc())
        .all()
    )
    return templates.TemplateResponse("distribution.html", {
        "request": request,
        "user": identity,
        "pending": pending,
        "completed": completed,
        "initiatives": initiatives,
        "channels": CHANNELS,
    })


@router.post("/distribution")
async def create_distribution_action(
    initiative_id: int = Form(default=None),
    channel: str = Form(...),
    description: str = Form(...),
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    action = models.DistributionAction(
        gateway_user_id=uid,
        initiative_id=initiative_id or None,
        channel=channel if channel in CHANNELS else "other",
        description=description.strip(),
        ai_suggested=False,
    )
    db.add(action)
    db.commit()
    return RedirectResponse("/distribution", status_code=303)


@router.post("/distribution/{action_id}/complete")
async def complete_action(
    action_id: int,
    impact_notes: str = Form(default=""),
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    action = _get_action(db, action_id, uid)
    action.status = "completed"
    action.impact_notes = impact_notes.strip()
    action.completed_at = datetime.utcnow()
    db.commit()

    await emit_event("MYTODO_DISTRIBUTION_COMPLETED", {
        "action_id": action.id,
        "channel": action.channel,
        "initiative_id": action.initiative_id,
        "user_id": uid,
    })

    return RedirectResponse("/distribution", status_code=303)


@router.post("/distribution/{action_id}/skip")
async def skip_action(
    action_id: int,
    identity: dict = Depends(_coo_or_above),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    action = _get_action(db, action_id, uid)
    action.status = "skipped"
    db.commit()
    return RedirectResponse("/distribution", status_code=303)


def _get_action(db: Session, action_id: int, uid: int) -> models.DistributionAction:
    action = db.query(models.DistributionAction).filter_by(
        id=action_id, gateway_user_id=uid
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Distribution action not found")
    return action

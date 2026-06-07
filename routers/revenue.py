"""
Revenue router — recording and displaying revenue per initiative.

OWNERSHIP MODEL (Phase 2):
  gateway_user_id = the user who recorded this entry.
  visibility controls who sees it:
    private → owner only (default — revenue is sensitive)
    team    → all approved workspace members

ACCESS RULES:
  Read:   founder sees all; others see own records + team-visible records.
  Create: any approved user except Viewer.
           Entry defaults to "private" unless the recorder chooses "team".
  The revenue total shown on the dashboard reflects visible records only.

Roles control AUTHORITY (user management), not feature access.
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

log = logging.getLogger("mytodo.revenue")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

SOURCES = ["subscription", "consulting", "client_payment", "freelance", "product_sale", "other"]

# Viewer is read-only — all other approved users can record revenue
_not_viewer = workspace_auth.require_role("founder", "coo", "staff")


def _visible_rev(db: Session, identity: dict):
    """Return a query for RevenueRecords visible to the current user."""
    uid  = identity["uid"]
    role = identity["role"]
    q    = db.query(models.RevenueRecord)
    if role == "founder":
        return q
    return q.filter(or_(
        models.RevenueRecord.gateway_user_id == uid,
        models.RevenueRecord.visibility == "team",
    ))


def _visible_initiatives(db: Session, identity: dict):
    """Initiatives the current user can see (to link revenue to)."""
    uid  = identity["uid"]
    role = identity["role"]
    q    = db.query(models.Initiative).filter_by(is_active=True)
    if role == "founder":
        return q
    return q.filter(or_(
        models.Initiative.gateway_user_id == uid,
        models.Initiative.visibility.in_(["team", "public"]),
    ))


@router.get("/revenue", response_class=HTMLResponse)
async def revenue_page(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    records = (
        _visible_rev(db, identity)
        .order_by(models.RevenueRecord.recorded_at.desc())
        .limit(50)
        .all()
    )
    initiatives = (
        _visible_initiatives(db, identity)
        .order_by(models.Initiative.revenue_total.desc())
        .all()
    )
    total = sum(r.amount for r in records)
    return templates.TemplateResponse("revenue.html", {
        "request":    request,
        "user":       identity,
        "records":    records,
        "initiatives": initiatives,
        "total":      total,
        "sources":    SOURCES,
        "can_record": identity["role"] != "viewer",
    })


@router.post("/revenue")
async def record_revenue(
    initiative_id: int = Form(...),
    amount: float = Form(...),
    source: str = Form(default="other"),
    notes: str = Form(default=""),
    visibility: str = Form(default="private"),
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    uid = identity["uid"]

    # Verify the initiative is visible to this user
    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, is_active=True
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")

    # Non-founders can only link revenue to visible initiatives
    role = identity["role"]
    if role != "founder":
        is_visible = (
            initiative.gateway_user_id == uid
            or initiative.visibility in ("team", "public")
        )
        if not is_visible:
            raise HTTPException(status_code=403, detail="Access denied")

    record = models.RevenueRecord(
        gateway_user_id=uid,
        initiative_id=initiative_id,
        amount=amount,
        source=source if source in SOURCES else "other",
        notes=notes.strip(),
        visibility=visibility if visibility in ("private", "team") else "private",
    )
    db.add(record)

    # Update initiative revenue total
    initiative.revenue_total = (initiative.revenue_total or 0) + amount
    initiative.updated_at    = datetime.utcnow()

    db.commit()
    db.refresh(record)

    await emit_event("MYTODO_REVENUE_RECORDED", {
        "record_id":       record.id,
        "initiative_id":   initiative_id,
        "initiative_name": initiative.name,
        "amount":          amount,
        "source":          source,
        "user_id":         uid,
    })

    return RedirectResponse("/revenue", status_code=303)

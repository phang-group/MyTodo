"""
Revenue router — recording and displaying revenue per initiative.

Every RevenueRecord updates initiative.revenue_total.
The Revenue Score is manually set by the founder — it reflects
perceived progress toward revenue goals, not just absolute numbers.
"""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
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


@router.get("/revenue", response_class=HTMLResponse)
async def revenue_page(
    request: Request,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    records = (
        db.query(models.RevenueRecord)
        .filter_by(gateway_user_id=uid)
        .order_by(models.RevenueRecord.recorded_at.desc())
        .limit(50)
        .all()
    )
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=uid, is_active=True)
        .order_by(models.Initiative.revenue_total.desc())
        .all()
    )
    total = sum(r.amount for r in records)
    return templates.TemplateResponse("revenue.html", {
        "request": request,
        "user": identity,
        "records": records,
        "initiatives": initiatives,
        "total": total,
        "sources": SOURCES,
    })


@router.post("/revenue")
async def record_revenue(
    initiative_id: int = Form(...),
    amount: float = Form(...),
    source: str = Form(default="other"),
    notes: str = Form(default=""),
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]

    # Verify initiative belongs to user
    initiative = db.query(models.Initiative).filter_by(
        id=initiative_id, gateway_user_id=uid
    ).first()
    if not initiative:
        raise HTTPException(status_code=404, detail="Initiative not found")

    record = models.RevenueRecord(
        gateway_user_id=uid,
        initiative_id=initiative_id,
        amount=amount,
        source=source if source in SOURCES else "other",
        notes=notes.strip(),
    )
    db.add(record)

    # Update initiative totals
    initiative.revenue_total = (initiative.revenue_total or 0) + amount
    initiative.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(record)

    await emit_event("MYTODO_REVENUE_RECORDED", {
        "record_id": record.id,
        "initiative_id": initiative_id,
        "initiative_name": initiative.name,
        "amount": amount,
        "source": source,
        "user_id": uid,
    })

    return RedirectResponse("/revenue", status_code=303)

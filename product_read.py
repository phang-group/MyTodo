"""
product_read.py — Product-layer read interface for PHANT consumption.

Lives in the product layer (mytodo root), not inside phant/.
PHANT imports these functions — never the raw models.

Rules:
- Read-only. No writes.
- Returns plain dicts or primitive types only.
- No SQLAlchemy model objects leak out.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models


def get_active_initiatives(
    db: Session,
    owner_user_id: int,
    is_founder: bool,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    q = db.query(models.Initiative).filter_by(is_active=True)
    if not is_founder:
        q = q.filter(or_(
            models.Initiative.gateway_user_id == owner_user_id,
            models.Initiative.visibility.in_(["team", "public"]),
        ))
    rows = q.all()
    return [
        {
            "name": i.name,
            "stage": i.stage,
            "build": i.build_score or 0,
            "distribution": i.distribution_score or 0,
            "revenue": i.revenue_score or 0,
            "revenue_total": i.revenue_total or 0,
        }
        for i in rows[:limit]
    ], len(rows)


def get_open_tasks(
    db: Session,
    owner_user_id: int,
) -> tuple[int, int]:
    """Returns (total_open, overdue_count)."""
    today = date.today()
    rows = (
        db.query(models.Task)
        .filter(
            models.Task.gateway_user_id == owner_user_id,
            models.Task.status.in_(["open", "in_progress"]),
        )
        .all()
    )
    overdue = sum(1 for t in rows if t.for_date and t.for_date < today)
    return len(rows), overdue


def get_week_revenue(
    db: Session,
    owner_user_id: int,
    days: int = 7,
) -> float:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(models.RevenueRecord)
        .filter(
            models.RevenueRecord.gateway_user_id == owner_user_id,
            models.RevenueRecord.recorded_at >= since,
        )
        .all()
    )
    return float(sum(r.amount or 0 for r in rows))


def get_pending_distribution_count(
    db: Session,
    owner_user_id: int,
) -> int:
    return (
        db.query(models.DistributionAction)
        .filter(
            models.DistributionAction.gateway_user_id == owner_user_id,
            models.DistributionAction.status == "pending",
        )
        .count()
    )

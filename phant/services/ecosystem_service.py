"""
phant/services/ecosystem_service.py — PHANT observing product reality.

This is the boundary in code. PHANT reads product execution state READ-ONLY to
answer live questions and to render Ecosystem Status. It never writes to product
tables. If a query here started mutating MyTodo data, the Identity Lock would be
violated.

V1 covers MyTodo (the host product). Each additional product gets one read
function returning a compact, structured snapshot — never the raw rows.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models  # MyTodo product models — read only

log = logging.getLogger("phant.ecosystem")


def _visible_initiatives(db: Session, owner_user_id: int, is_founder: bool):
    q = db.query(models.Initiative).filter_by(is_active=True)
    if is_founder:
        return q
    return q.filter(or_(
        models.Initiative.gateway_user_id == owner_user_id,
        models.Initiative.visibility.in_(["team", "public"]),
    ))


def get_mytodo_context(db: Session, owner_user_id: int,
                       is_founder: bool = True) -> Dict[str, Any]:
    """A compact, read-only snapshot of MyTodo execution state."""
    try:
        initiatives = _visible_initiatives(db, owner_user_id, is_founder).all()

        today = date.today()
        open_tasks = (
            db.query(models.Task)
            .filter(models.Task.gateway_user_id == owner_user_id,
                    models.Task.status.in_(["open", "in_progress"]))
            .all()
        )
        overdue = [t for t in open_tasks if t.for_date and t.for_date < today]

        week_start = datetime.utcnow() - timedelta(days=7)
        revenue_week = (
            db.query(models.RevenueRecord)
            .filter(models.RevenueRecord.gateway_user_id == owner_user_id,
                    models.RevenueRecord.recorded_at >= week_start)
            .all()
        )
        revenue_week_total = sum(r.amount or 0 for r in revenue_week)

        pending_distribution = (
            db.query(models.DistributionAction)
            .filter(models.DistributionAction.gateway_user_id == owner_user_id,
                    models.DistributionAction.status == "pending")
            .count()
        )

        # The initiative whose distribution most lags its build — the typical gap.
        bottleneck = None
        worst_gap = -1
        for i in initiatives:
            gap = (i.build_score or 0) - (i.distribution_score or 0)
            if gap > worst_gap:
                worst_gap = gap
                bottleneck = i

        return {
            "product": "mytodo",
            "available": True,
            "active_initiatives": len(initiatives),
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue),
            "revenue_last_7d": revenue_week_total,
            "pending_distribution_actions": pending_distribution,
            "initiatives": [
                {
                    "name": i.name,
                    "stage": i.stage,
                    "build": i.build_score or 0,
                    "distribution": i.distribution_score or 0,
                    "revenue": i.revenue_score or 0,
                    "revenue_total": i.revenue_total or 0,
                }
                for i in initiatives[:8]
            ],
            "primary_bottleneck": (
                {"initiative": bottleneck.name, "build_minus_distribution": worst_gap}
                if bottleneck and worst_gap > 0 else None
            ),
        }
    except Exception as e:  # noqa: BLE001 — product read must never crash PHANT
        log.warning("MyTodo ecosystem read failed: %s", e)
        return {"product": "mytodo", "available": False, "error": str(e)}


def snapshot(db: Session, owner_user_id: int, is_founder: bool = True) -> Dict[str, Any]:
    """
    Full ecosystem snapshot across all observable products. As products come
    online, add their read function here. PHANT's awareness grows by observing
    more product reality — not by adding PHANT features.
    """
    return {
        "mytodo": get_mytodo_context(db, owner_user_id, is_founder),
        # "infopro":  get_infopro_context(...),   # when InfoPro exposes a read API
        # "nextdoor": get_nextdoor_context(...),  # when NextDoor exposes a read API
    }


def snapshot_text(snap: Dict[str, Any]) -> str:
    """Render a snapshot as compact text for an LLM prompt."""
    mt = snap.get("mytodo", {})
    if not mt.get("available"):
        return "MyTodo: snapshot unavailable."
    lines = [
        "MyTodo (execution state):",
        f"- Active initiatives: {mt['active_initiatives']}",
        f"- Open tasks: {mt['open_tasks']} (overdue: {mt['overdue_tasks']})",
        f"- Revenue last 7 days: NGN {mt['revenue_last_7d']:,.0f}",
        f"- Pending distribution actions: {mt['pending_distribution_actions']}",
    ]
    if mt.get("primary_bottleneck"):
        b = mt["primary_bottleneck"]
        lines.append(f"- Biggest build/distribution gap: {b['initiative']} (+{b['build_minus_distribution']})")
    for i in mt.get("initiatives", [])[:6]:
        lines.append(
            f"  · {i['name']} [{i['stage']}] build {i['build']} / dist {i['distribution']} / rev {i['revenue']}"
        )
    return "\n".join(lines)

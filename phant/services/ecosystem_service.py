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
from typing import Any, Dict

from sqlalchemy.orm import Session

import product_read  # product-layer read interface — no raw model access from here

log = logging.getLogger("phant.ecosystem")


def get_mytodo_context(db: Session, owner_user_id: int,
                       is_founder: bool = True) -> Dict[str, Any]:
    """A compact, read-only snapshot of MyTodo execution state."""
    try:
        initiatives, total_count = product_read.get_active_initiatives(
            db, owner_user_id, is_founder
        )
        open_tasks, overdue = product_read.get_open_tasks(db, owner_user_id)
        revenue_week_total = product_read.get_week_revenue(db, owner_user_id)
        pending_distribution = product_read.get_pending_distribution_count(
            db, owner_user_id
        )

        bottleneck = None
        worst_gap = -1
        for i in initiatives:
            gap = i["build"] - i["distribution"]
            if gap > worst_gap:
                worst_gap = gap
                bottleneck = i

        return {
            "product": "mytodo",
            "available": True,
            "active_initiatives": total_count,
            "open_tasks": open_tasks,
            "overdue_tasks": overdue,
            "revenue_last_7d": revenue_week_total,
            "pending_distribution_actions": pending_distribution,
            "initiatives": initiatives,
            "primary_bottleneck": (
                {"initiative": bottleneck["name"], "build_minus_distribution": worst_gap}
                if bottleneck and worst_gap > 0 else None
            ),
        }
    except Exception as e:  # noqa: BLE001 — product read must never crash PHANT
        log.warning("MyTodo ecosystem read failed: %s", e)
        # Rollback so subsequent queries on the same DB session are not poisoned
        # by a failed psycopg2 transaction (InFailedSqlTransaction).
        try:
            db.rollback()
        except Exception:
            pass
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

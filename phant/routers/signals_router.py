"""
phant/routers/signals_router.py — GET /phant/signals/{type}

This replaces the unimplemented endpoint that phant.js has been calling since the
panel was built. It routes to the correct PHANT data layer based on signal type:

    risks         — active risk memories
    goals         — active goal memories
    commitments   — active commitment memories
    decisions     — recent decisions (pending or confirmed with no outcome)
    divergences   — unresolved divergences
    patterns      — high-confidence pattern memories
    recent        — all recent memories (last 48h)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..repositories import MemoryRepository, DecisionRepository, DivergenceRepository

router = APIRouter(prefix="/phant", tags=["phant-signals"])


@router.get("/signals/{signal_type}")
def get_signals(
    signal_type: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    mrepo = MemoryRepository(db)

    if signal_type == "risks":
        items = mrepo.active_risks(owner_user_id)
        return JSONResponse(content={"type": "risks", "items": [m.to_dict() for m in items]})

    if signal_type == "goals":
        items = mrepo.goals(owner_user_id)
        return JSONResponse(content={"type": "goals", "items": [m.to_dict() for m in items]})

    if signal_type == "commitments":
        items = mrepo.commitments(owner_user_id)
        return JSONResponse(content={"type": "commitments", "items": [m.to_dict() for m in items]})

    if signal_type == "patterns":
        items = mrepo.by_type(owner_user_id, "pattern")
        return JSONResponse(content={"type": "patterns", "items": [m.to_dict() for m in items]})

    if signal_type == "decisions":
        # Pending + recently confirmed with no outcome
        decisions = DecisionRepository(db).list(owner_user_id, status="pending", limit=20)
        orphans   = DecisionRepository(db).orphaned(owner_user_id)
        seen = {d.id for d in decisions}
        for d in orphans:
            if d.id not in seen:
                decisions.append(d)
        return JSONResponse(content={
            "type": "decisions",
            "items": [d.to_dict() for d in decisions[:20]],
        })

    if signal_type == "divergences":
        items = DivergenceRepository(db).unresolved(owner_user_id, limit=20)
        return JSONResponse(content={"type": "divergences", "items": [d.to_dict() for d in items]})

    # Default: recent memories
    items = mrepo.recent(owner_user_id, hours=48, limit=20)
    return JSONResponse(content={"type": "recent", "items": [m.to_dict() for m in items]})

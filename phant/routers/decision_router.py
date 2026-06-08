"""phant/routers/decision_router.py — POST /phant/decisions, POST /phant/outcomes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..schemas import DecisionIn, OutcomeIn
from ..services import decision_service
from ..repositories import DecisionRepository, OutcomeRepository

router = APIRouter(prefix="/phant", tags=["phant-decisions"])


@router.post("/decisions")
def create_decision(
    payload: DecisionIn,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    decision = decision_service.create_decision(db, owner_user_id, payload)
    return JSONResponse(content=decision.to_dict(), status_code=201)


@router.get("/decisions")
def list_decisions(
    context_id: Optional[str] = Query(None),
    domain: Optional[str]     = Query(None),
    status: Optional[str]     = Query(None),
    limit: int                = Query(50, ge=1, le=200),
    with_outcomes: bool       = Query(False),
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)

    if with_outcomes:
        pairs = decision_service.list_decisions_with_outcomes(
            db, owner_user_id, context_id=context_id, domain=domain,
            status=status, limit=limit,
        )
        items = []
        for d, o in pairs:
            row = d.to_dict()
            row["outcome"] = o.to_dict() if o else None
            items.append(row)
        return JSONResponse(content={"decisions": items, "count": len(items)})

    decisions = DecisionRepository(db).list(
        owner_user_id, context_id=context_id, domain=domain, status=status, limit=limit
    )
    return JSONResponse(content={
        "decisions": [d.to_dict() for d in decisions],
        "count": len(decisions),
    })


@router.get("/decisions/{decision_id}")
def get_decision(
    decision_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    decision = DecisionRepository(db).get(decision_id)
    if not decision or decision.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)
    outcomes = OutcomeRepository(db).for_decision(decision_id)
    result = decision.to_dict()
    result["outcomes"] = [o.to_dict() for o in outcomes]
    return JSONResponse(content=result)


@router.post("/outcomes")
def record_outcome(
    payload: OutcomeIn,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    try:
        outcome = decision_service.record_outcome(db, owner_user_id, payload)
        return JSONResponse(content=outcome.to_dict(), status_code=201)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=404)
    except PermissionError as e:
        return JSONResponse(content={"error": str(e)}, status_code=403)


@router.get("/calibration")
def calibration_summary(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    summary = decision_service.calibration_summary(db, owner_user_id)
    return JSONResponse(content=summary)

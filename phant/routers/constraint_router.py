"""phant/routers/constraint_router.py — constraint management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..schemas import ConstraintIn, ConstraintDeactivate
from ..repositories import ContextRepository, ConstraintRepository

router = APIRouter(prefix="/phant", tags=["phant-constraints"])


@router.post("/constraints")
def create_constraint(
    payload: ConstraintIn,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    context_id = None
    if payload.context:
        ctx = ContextRepository(db).get_or_create(owner_user_id, payload.context)
        context_id = ctx.id

    constraint = ConstraintRepository(db).create(
        owner_user_id=owner_user_id,
        context_id=context_id,
        content=payload.content,
        constraint_type=payload.constraint_type,
        is_hard_constraint=payload.is_hard_constraint,
    )
    return JSONResponse(content=constraint.to_dict(), status_code=201)


@router.get("/constraints")
def list_constraints(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    constraints = ConstraintRepository(db).all_active(owner_user_id)
    return JSONResponse(content={
        "constraints": [c.to_dict() for c in constraints],
        "count": len(constraints),
    })


@router.patch("/constraints/{constraint_id}/deactivate")
def deactivate_constraint(
    constraint_id: str,
    payload: ConstraintDeactivate,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    repo = ConstraintRepository(db)
    constraint = repo.get(constraint_id)
    if not constraint or constraint.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)
    updated = repo.deactivate(constraint, payload.deactivation_reason or "")
    return JSONResponse(content=updated.to_dict())

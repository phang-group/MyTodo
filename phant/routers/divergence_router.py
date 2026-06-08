"""phant/routers/divergence_router.py — divergence management endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..schemas import DivergenceResolve
from ..services import divergence_service
from ..repositories import DivergenceRepository

router = APIRouter(prefix="/phant", tags=["phant-divergences"])


@router.get("/divergences")
def list_divergences(
    status: Optional[str] = Query(None),
    limit: int            = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    divergences = DivergenceRepository(db).list(owner_user_id, status=status, limit=limit)
    return JSONResponse(content={
        "divergences": [d.to_dict() for d in divergences],
        "count": len(divergences),
    })


@router.post("/divergences/detect")
async def run_detection(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    """Manually trigger divergence detection. Returns unresolved divergences after scan."""
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    divergences = await divergence_service.detect_all(db, owner_user_id)
    return JSONResponse(content={
        "divergences": [d.to_dict() for d in divergences],
        "count": len(divergences),
    })


@router.patch("/divergences/{divergence_id}")
def resolve_divergence(
    divergence_id: str,
    payload: DivergenceResolve,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    repo = DivergenceRepository(db)
    div = repo.get(divergence_id)
    if not div or div.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)
    valid_statuses = {"acknowledged", "resolved", "dismissed"}
    if payload.status not in valid_statuses:
        return JSONResponse(
            content={"error": f"status must be one of {valid_statuses}"},
            status_code=422,
        )
    updated = repo.resolve(div, payload.status, payload.resolution_note)
    return JSONResponse(content=updated.to_dict())

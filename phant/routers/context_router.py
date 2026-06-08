"""phant/routers/context_router.py — GET /phant/context/{id}, GET /phant/contexts."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..repositories import ContextRepository, MemoryRepository

router = APIRouter(prefix="/phant", tags=["phant-context"])


@router.get("/contexts")
def list_contexts(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    contexts = ContextRepository(db).list(owner_user_id, active_only=False)
    return JSONResponse(content={
        "contexts": [c.to_dict() for c in contexts],
        "count": len(contexts),
    })


@router.get("/context/{context_id}")
def get_context(
    context_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    ctx = ContextRepository(db).get(context_id)
    if not ctx or ctx.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)

    memory_count = MemoryRepository(db).counts_by_context(owner_user_id, context_id)
    result = ctx.to_dict()
    result["memory_count"] = memory_count
    return JSONResponse(content=result)

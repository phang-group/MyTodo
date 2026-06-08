"""phant/routers/memory_router.py — POST /phant/memories, GET /phant/memories."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..schemas import MemoryIn, ConfidenceUpdate
from ..services import memory_service
from ..repositories import MemoryRepository

router = APIRouter(prefix="/phant", tags=["phant-memories"])


@router.post("/memories")
async def create_memory(
    payload: MemoryIn,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    mem = await memory_service.create_memory(
        db,
        owner_user_id=owner_user_id,
        content=payload.content,
        memory_type=payload.memory_type,
        product_source=payload.product_source,
        context_name=payload.context,
        confidence=payload.confidence,
        is_verified=payload.is_verified,
        metadata=payload.metadata,
        source_event_id=payload.source_event_id,
    )
    return JSONResponse(content=mem.to_dict(), status_code=201)


@router.get("/memories")
def list_memories(
    context_id: Optional[str]   = Query(None),
    memory_type: Optional[str]  = Query(None),
    product: Optional[str]      = Query(None),
    search: Optional[str]       = Query(None),
    status: Optional[str]       = Query("active"),
    limit: int                  = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    types = [memory_type] if memory_type else None
    memories = MemoryRepository(db).query(
        owner_user_id,
        context_id=context_id,
        types=types,
        product=product,
        search=search,
        status=status,
        limit=limit,
    )
    return JSONResponse(content={"memories": [m.to_dict() for m in memories], "count": len(memories)})


@router.patch("/memories/{memory_id}/confidence")
def update_confidence(
    memory_id: str,
    payload: ConfidenceUpdate,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    repo = MemoryRepository(db)
    mem = repo.get(memory_id)
    if not mem or mem.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)
    updated = repo.update_confidence(mem, payload.confidence, payload.reason)
    return JSONResponse(content=updated.to_dict())


@router.delete("/memories/{memory_id}")
def archive_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    repo = MemoryRepository(db)
    mem = repo.get(memory_id)
    if not mem or mem.owner_user_id != owner_user_id:
        return JSONResponse(content={"error": "not_found"}, status_code=404)
    repo.archive(mem)
    return JSONResponse(content={"archived": True, "id": memory_id})

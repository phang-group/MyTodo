"""phant/routers/brief_router.py — GET /phant/brief/daily."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..services import brief_service

router = APIRouter(prefix="/phant", tags=["phant-brief"])


@router.get("/brief/daily")
async def daily_brief(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    is_founder = identity.get("role") in ("founder", "admin")
    result = await brief_service.generate_daily_brief(db, owner_user_id, is_founder=is_founder)
    return JSONResponse(content=result)

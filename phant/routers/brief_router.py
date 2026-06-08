"""phant/routers/brief_router.py — GET /phant/brief/daily."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..services import brief_service

router = APIRouter(prefix="/phant", tags=["phant-brief"])


import logging as _log
_brief_log = _log.getLogger("phant.brief.router")


@router.get("/brief/daily")
async def daily_brief(
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)
    is_founder = identity.get("role") in ("founder", "admin")
    try:
        result = await brief_service.generate_daily_brief(db, owner_user_id, is_founder=is_founder)
        return JSONResponse(content=result)
    except Exception as _e:
        import traceback
        _brief_log.error("BRIEF 500 — %s\n%s", _e, traceback.format_exc())
        return JSONResponse(
            content={"error": type(_e).__name__, "detail": str(_e), "brief": None},
            status_code=500,
        )

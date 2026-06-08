"""phant/routers/chat_router.py — POST /phant/chat (elephant-button doorway)."""

from __future__ import annotations

import logging
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from gateway_auth import require_identity
from ..schemas import ChatIn
from ..services import chat_service

router = APIRouter(prefix="/phant", tags=["phant-chat"])
log = logging.getLogger("phant.chat.router")


@router.post("/chat")
async def phant_chat(
    payload: ChatIn,
    db: Session = Depends(get_db),
    identity: dict = Depends(require_identity),
):
    owner_user_id = int(identity.get("user_id") or identity.get("uid") or 1)

    try:
        result = await chat_service.chat(
            db,
            owner_user_id,
            payload.message,
            context_name=payload.context,
            session_id=payload.session_id,
            page=payload.page,
            product=payload.product,
        )
        return JSONResponse(content={
            "response":   result["response"],
            "mode":       result["mode"],
            "session_id": result["session_id"],
        })
    except Exception as exc:
        log.error("CHAT 500 — %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            content={"error": "chat_failed", "response": None},
            status_code=500,
        )

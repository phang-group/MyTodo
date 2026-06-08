"""phant/routers/event_router.py — POST /phant/events (product event ingestion)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from ..schemas import EventIn
from ..services import ingest_service

router = APIRouter(prefix="/phant", tags=["phant-events"])


def _verify_event_token(x_phant_token: str = Header(default="")) -> None:
    """
    Events come from products — not from the browser. They authenticate with a
    shared token (PHANG_ADMIN_SECRET), not a user cookie.

    Products that fire events internally (same process — e.g. MyTodo) can skip
    auth by setting x_phant_token to the admin secret. External products must
    obtain it through their own deployment environment.
    """
    expected = os.getenv("PHANG_ADMIN_SECRET", "")
    if not expected:
        return  # token not configured — accept all (dev mode)
    if x_phant_token != expected:
        raise HTTPException(status_code=401, detail="invalid event token")


@router.post("/events")
async def ingest_event(
    payload: EventIn,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_event_token),
):
    event_dict = payload.model_dump()
    result = await ingest_service.ingest(db, event_dict)
    return JSONResponse(content=result, status_code=200)

import json
import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import ai_copilot
import gateway_auth
import models
from database import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
log = logging.getLogger("mytodo.copilot")


@router.get("/copilot", response_class=HTMLResponse)
async def copilot_page(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    user_id = identity["user_id"]
    history = (
        db.query(models.ChatMessage)
        .filter_by(gateway_user_id=user_id)
        .order_by(models.ChatMessage.created_at.asc())
        .limit(50)
        .all()
    )
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=user_id, is_active=True)
        .order_by(models.Initiative.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse("copilot.html", {
        "request": request,
        "user": identity,
        "history": history,
        "initiatives": initiatives,
        "initiative_count": len(initiatives),
    })


@router.post("/copilot/chat")
async def copilot_chat(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    user_id = identity["user_id"]

    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    # Save user message
    user_msg = models.ChatMessage(
        gateway_user_id=user_id,
        role="user",
        content=message,
    )
    db.add(user_msg)
    db.commit()

    # Route to daily brief if DAILY_PLANNING
    result = await ai_copilot.process_message(message, db, user_id)

    if result["show_brief"]:
        brief = await ai_copilot.generate_daily_brief(db, user_id)
        response_text = _format_brief_text(brief)
        intent = "DAILY_PLANNING"
        actions = []
    else:
        response_text = result["response"]
        intent = result["intent"]
        actions = result["actions_taken"]

    # Save assistant message
    assistant_msg = models.ChatMessage(
        gateway_user_id=user_id,
        role="assistant",
        content=response_text,
        intent=intent,
        actions_taken=json.dumps(actions),
    )
    db.add(assistant_msg)
    db.commit()

    return JSONResponse({
        "response": response_text,
        "intent": intent,
        "actions_taken": actions,
        "message_id": assistant_msg.id,
    })


@router.get("/daily-brief", response_class=HTMLResponse)
async def daily_brief_page(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    user_id = identity["user_id"]
    brief = await ai_copilot.generate_daily_brief(db, user_id)
    initiatives = (
        db.query(models.Initiative)
        .filter_by(gateway_user_id=user_id, is_active=True)
        .all()
    )
    return templates.TemplateResponse("daily_brief.html", {
        "request": request,
        "user": identity,
        "brief": brief,
        "initiatives": initiatives,
        "today": date.today().isoformat(),
    })


def _format_brief_text(brief: dict) -> str:
    """Convert brief dict to conversational Telegram-style text."""
    lines = []
    headline = brief.get("headline", "")
    if headline:
        lines.append(f"**{headline}**\n")

    top = brief.get("top_priority")
    if top:
        lines.append(f"Top priority: *{top.get('initiative')}* — {top.get('reason', '')}")
        lines.append(f"Bottleneck: {top.get('bottleneck', 'distribution')}\n")

    actions = brief.get("actions", [])
    if actions:
        lines.append("Actions for today:")
        for a in actions:
            lines.append(f"• {a}")

    return "\n".join(lines)

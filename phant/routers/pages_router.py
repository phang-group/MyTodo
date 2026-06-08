"""phant/routers/pages_router.py — PHANT full-page HTML views."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from gateway_auth import require_identity

router = APIRouter(tags=["phant-pages"])

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/phant", response_class=HTMLResponse)
async def phant_home(
    request: Request,
    identity: dict = Depends(require_identity),
):
    return templates.TemplateResponse("phant/home.html", {
        "request": request,
        "user":    identity,
    })


@router.get("/phant/intelligence", response_class=HTMLResponse)
async def phant_intelligence(
    request: Request,
    identity: dict = Depends(require_identity),
):
    return templates.TemplateResponse("phant/intelligence.html", {
        "request": request,
        "user":    identity,
    })


@router.get("/phant/memory", response_class=HTMLResponse)
async def phant_memory_explorer(
    request: Request,
    identity: dict = Depends(require_identity),
):
    return templates.TemplateResponse("phant/memory_explorer.html", {
        "request": request,
        "user":    identity,
    })


@router.get("/phant/constraints-page", response_class=HTMLResponse)
async def phant_constraints_page(
    request: Request,
    identity: dict = Depends(require_identity),
):
    return templates.TemplateResponse("phant/constraints.html", {
        "request": request,
        "user":    identity,
    })


@router.get("/phant/chat-page", response_class=HTMLResponse)
async def phant_chat_page(
    request: Request,
    identity: dict = Depends(require_identity),
):
    return templates.TemplateResponse("phant/chat.html", {
        "request": request,
        "user":    identity,
    })

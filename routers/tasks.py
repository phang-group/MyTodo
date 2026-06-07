"""
Tasks router — discrete actions tied to initiatives.
"""

import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import gateway_auth
import models
from database import get_db
from .events import emit_event

log = logging.getLogger("mytodo.tasks")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_CATEGORIES = {"build", "distribution", "revenue", "ops", "learning"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


@router.post("/tasks")
async def create_task(
    initiative_id: int = Form(default=None),
    title: str = Form(...),
    notes: str = Form(default=""),
    category: str = Form(default="build"),
    priority: str = Form(default="high"),
    for_date: str = Form(default=""),
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]

    parsed_date = date.today()
    if for_date:
        try:
            parsed_date = date.fromisoformat(for_date)
        except ValueError:
            pass

    task = models.Task(
        gateway_user_id=uid,
        initiative_id=initiative_id or None,
        title=title.strip(),
        notes=notes.strip(),
        category=category if category in VALID_CATEGORIES else "build",
        priority=priority if priority in VALID_PRIORITIES else "high",
        for_date=parsed_date,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    redirect = f"/initiatives/{initiative_id}" if initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


@router.post("/tasks/{task_id}/done")
async def mark_done(
    request: Request,
    task_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    task = _get_task(db, task_id, uid)
    task.status = "done"
    task.done_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    db.commit()

    await emit_event("MYTODO_TASK_COMPLETED", {
        "task_id": task.id,
        "title": task.title,
        "category": task.category,
        "initiative_id": task.initiative_id,
        "user_id": uid,
    })

    # AJAX-friendly: return JSON if XHR, else redirect
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({"status": "done", "task_id": task_id})
    redirect = f"/initiatives/{task.initiative_id}" if task.initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


@router.post("/tasks/{task_id}/reopen")
async def reopen_task(
    task_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    task = _get_task(db, task_id, uid)
    task.status = "open"
    task.done_at = None
    task.updated_at = datetime.utcnow()
    db.commit()
    redirect = f"/initiatives/{task.initiative_id}" if task.initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


@router.post("/tasks/{task_id}/skip")
async def skip_task(
    task_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    task = _get_task(db, task_id, uid)
    task.status = "skipped"
    task.updated_at = datetime.utcnow()
    db.commit()
    redirect = f"/initiatives/{task.initiative_id}" if task.initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


@router.post("/tasks/{task_id}/delete")
async def delete_task(
    task_id: int,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    task = _get_task(db, task_id, uid)
    initiative_id = task.initiative_id
    db.delete(task)
    db.commit()
    redirect = f"/initiatives/{initiative_id}" if initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


def _get_task(db: Session, task_id: int, uid: int) -> models.Task:
    task = db.query(models.Task).filter_by(id=task_id, gateway_user_id=uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

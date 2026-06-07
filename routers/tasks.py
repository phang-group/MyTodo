"""
Tasks router — discrete actions tied to initiatives.

Phase 2 additions:
  - assigned_to_user_id: tasks can be assigned to a specific workspace member
  - Role-aware access: founder/coo see all tasks; staff see only assigned tasks
"""

import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import gateway_auth
import workspace_auth
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
    assigned_to: int = Form(default=None),    # workspace_user.id (optional)
    identity: dict = Depends(workspace_auth.require_role("founder", "coo")),
    db: Session = Depends(get_db),
):
    uid = identity["uid"]

    parsed_date = date.today()
    if for_date:
        try:
            parsed_date = date.fromisoformat(for_date)
        except ValueError:
            pass

    task = models.Task(
        gateway_user_id=1,             # tasks always owned by founder workspace
        initiative_id=initiative_id or None,
        title=title.strip(),
        notes=notes.strip(),
        category=category if category in VALID_CATEGORIES else "build",
        priority=priority if priority in VALID_PRIORITIES else "high",
        for_date=parsed_date,
        assigned_to_user_id=assigned_to or None,
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
    task = _get_task(db, task_id, identity)
    task.status   = "done"
    task.done_at  = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    db.commit()

    await emit_event("MYTODO_TASK_COMPLETED", {
        "task_id":       task.id,
        "title":         task.title,
        "category":      task.category,
        "initiative_id": task.initiative_id,
        "completed_by":  identity["email"],
        "user_id":       identity["uid"],
    })

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
    task = _get_task(db, task_id, identity)
    task.status   = "open"
    task.done_at  = None
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
    task = _get_task(db, task_id, identity)
    task.status = "skipped"
    task.updated_at = datetime.utcnow()
    db.commit()
    redirect = f"/initiatives/{task.initiative_id}" if task.initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


@router.post("/tasks/{task_id}/delete")
async def delete_task(
    task_id: int,
    identity: dict = Depends(workspace_auth.require_role("founder", "coo")),
    db: Session = Depends(get_db),
):
    task = _get_task(db, task_id, identity)
    initiative_id = task.initiative_id
    db.delete(task)
    db.commit()
    redirect = f"/initiatives/{initiative_id}" if initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_task(db: Session, task_id: int, identity: dict) -> models.Task:
    """Load task with role-based access control."""
    task = db.query(models.Task).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    role = identity["role"]
    uid  = identity["uid"]

    if role in ("founder", "coo"):
        return task   # full access

    if role == "staff" and task.assigned_to_user_id == uid:
        return task   # can act on their own assigned tasks

    raise HTTPException(status_code=403, detail="Access denied")

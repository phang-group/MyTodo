"""
Tasks router — discrete actions tied to initiatives.

OWNERSHIP MODEL (Phase 2):
  gateway_user_id = the user who created/owns this task.
  visibility controls who can see it:
    private  → owner only
    team     → all approved workspace members (default)
    public   → all approved workspace members

ACCESS RULES:
  Create: any approved user (not viewer).
  Read/complete/reopen/skip: owner, assigned user, or team/public visibility.
  Delete: owner or founder.

Roles control AUTHORITY, not product access.
"""

import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
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

# All approved users except Viewer can create/modify tasks
_not_viewer = workspace_auth.require_role("founder", "coo", "staff")


@router.post("/tasks")
async def create_task(
    initiative_id: int = Form(default=None),
    title: str = Form(...),
    notes: str = Form(default=""),
    category: str = Form(default="build"),
    priority: str = Form(default="high"),
    for_date: str = Form(default=""),
    visibility: str = Form(default="team"),
    assigned_to: int = Form(default=None),    # workspace_user.id (optional)
    identity: dict = Depends(_not_viewer),
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
        gateway_user_id=uid,                  # owned by the creating user
        initiative_id=initiative_id or None,
        title=title.strip(),
        notes=notes.strip(),
        category=category if category in VALID_CATEGORIES else "build",
        priority=priority if priority in VALID_PRIORITIES else "high",
        for_date=parsed_date,
        visibility=visibility if visibility in ("private", "team", "public") else "team",
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
    task.status    = "done"
    task.done_at   = datetime.utcnow()
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
    task.status    = "open"
    task.done_at   = None
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
    identity: dict = Depends(_not_viewer),
    db: Session = Depends(get_db),
):
    task = _get_task(db, task_id, identity, require_owner=True)
    initiative_id = task.initiative_id
    db.delete(task)
    db.commit()
    redirect = f"/initiatives/{initiative_id}" if initiative_id else "/"
    return RedirectResponse(redirect, status_code=303)


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_task(
    db: Session, task_id: int, identity: dict, require_owner: bool = False
) -> models.Task:
    """
    Load a task with visibility check.

    Visibility rules:
      Founder       → sees all tasks.
      Other users   → see tasks they own, tasks assigned to them,
                       or tasks with team/public visibility.

    require_owner=True: only the owner or founder may proceed
    (used for delete — you can't delete someone else's task).
    """
    task = db.query(models.Task).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    uid  = identity["uid"]
    role = identity["role"]

    # Founder override
    if role == "founder":
        return task

    # Visibility: own task, assigned task, or team/public
    can_see = (
        task.gateway_user_id == uid
        or task.assigned_to_user_id == uid
        or task.visibility in ("team", "public")
    )
    if not can_see:
        raise HTTPException(status_code=403, detail="Access denied")

    # For ownership-required operations (delete)
    if require_owner and task.gateway_user_id != uid:
        raise HTTPException(status_code=403, detail="Only the task owner can perform this action")

    return task

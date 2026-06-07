"""
Users router — workspace member management (Founder only).

Routes:
  GET  /users                  — list all users
  POST /users/invite           — generate invite link
  POST /users/{id}/approve     — approve pending user
  POST /users/{id}/suspend     — suspend user
  POST /users/{id}/unsuspend   — restore suspended user
  POST /users/{id}/role        — change user role

All routes require Founder role. COO/Staff/Viewer receive 403.
"""
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
import workspace_auth
from database import get_db
from .events import (
    emit_user_invited, emit_user_approved,
    emit_user_suspended, emit_role_changed,
)

log = logging.getLogger("mytodo.users")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

VALID_ROLES = ("founder", "coo", "staff", "viewer")
INVITE_TTL_HOURS = 72


# ── User list ─────────────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    users = db.query(models.WorkspaceUser).order_by(
        models.WorkspaceUser.role.asc(),
        models.WorkspaceUser.created_at.asc(),
    ).all()

    # Active invites (unused, not expired)
    pending_invites = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.used == False,
        models.WorkspaceInvite.expires_at > datetime.utcnow(),
    ).order_by(models.WorkspaceInvite.created_at.desc()).all()

    return templates.TemplateResponse("users.html", {
        "request": request,
        "user": identity,
        "users": users,
        "pending_invites": pending_invites,
        "roles": VALID_ROLES,
    })


# ── Invite creation ───────────────────────────────────────────────────────────

@router.post("/users/invite")
async def invite_user(
    request: Request,
    email: str = Form(...),
    role: str = Form(default="viewer"),
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    role  = role if role in VALID_ROLES else "viewer"

    # Don't invite if already a member
    existing = db.query(models.WorkspaceUser).filter_by(email=email).first()
    if existing:
        return RedirectResponse(
            f"/users?error=User+{email}+already+exists", status_code=303
        )

    # Cancel any outstanding unused invite for this email
    db.query(models.WorkspaceInvite).filter_by(email=email, used=False).delete()

    invite = models.WorkspaceInvite(
        token=uuid.uuid4().hex,
        email=email,
        role=role,
        created_by=identity["uid"],
        expires_at=datetime.utcnow() + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    log.info("Invite created: %s role=%s token=%s", email, role, invite.token[:8] + "...")
    await emit_user_invited(email=email, role=role, invited_by=identity["email"])

    return RedirectResponse(f"/users?invite_token={invite.token}", status_code=303)


# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: int,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    user.status = "approved"
    user.updated_at = datetime.utcnow()
    db.commit()
    log.info("User approved: %s", user.email)
    await emit_user_approved(email=user.email, role=user.role, approved_by=identity["email"])
    return RedirectResponse("/users", status_code=303)


# ── Suspend / unsuspend ───────────────────────────────────────────────────────

@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: int,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    if user.role == "founder" and user.id == identity["uid"]:
        raise HTTPException(400, detail="Cannot suspend yourself")
    user.status = "suspended"
    user.updated_at = datetime.utcnow()
    db.commit()
    log.info("User suspended: %s", user.email)
    await emit_user_suspended(email=user.email, suspended_by=identity["email"])
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: int,
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    user.status = "approved"
    user.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/users", status_code=303)


# ── Role change ───────────────────────────────────────────────────────────────

@router.post("/users/{user_id}/role")
async def change_role(
    user_id: int,
    role: str = Form(...),
    identity: dict = Depends(workspace_auth.require_role("founder")),
    db: Session = Depends(get_db),
):
    if role not in VALID_ROLES:
        raise HTTPException(400, detail="Invalid role")
    user = _get_user(db, user_id)
    if user.id == identity["uid"] and role != "founder":
        raise HTTPException(400, detail="Cannot change your own founder role")

    old_role = user.role
    user.role = role
    user.updated_at = datetime.utcnow()
    db.commit()

    log.info("Role changed: %s %s → %s", user.email, old_role, role)
    await emit_role_changed(
        email=user.email,
        old_role=old_role,
        new_role=role,
        changed_by=identity["email"],
    )
    return RedirectResponse("/users", status_code=303)


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_user(db: Session, user_id: int) -> models.WorkspaceUser:
    user = db.query(models.WorkspaceUser).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")
    return user

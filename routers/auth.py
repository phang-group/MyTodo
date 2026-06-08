"""
Auth router — login, logout, invite acceptance.

Phase 2 flow:
  - All users: email + password
  - Founder: email = MYTODO_OWNER_EMAIL, password = MYTODO_ACCESS_CODE (bootstrapped)
  - Team members: accept invite link → set password → email+password thereafter

Routes:
  GET  /login
  POST /login
  POST /logout
  GET  /invite/{token}
  POST /invite/{token}/accept
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
import workspace_auth
from database import get_db

log = logging.getLogger("mytodo.auth")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ── Login ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", success: str = ""):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "success": success,
    })


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(default=""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    import os
    email = email.strip().lower()

    # Access-code-only path: no email supplied → match against MYTODO_ACCESS_CODE
    # and sign in as the founder. Used by COO / testers who only know the code.
    if not email:
        access_code = os.getenv("MYTODO_ACCESS_CODE", "").strip()
        if access_code and password.strip() == access_code:
            user = db.query(models.WorkspaceUser).filter_by(role="founder").first()
            if not user:
                return templates.TemplateResponse(
                    "login.html",
                    {"request": request, "error": "Founder account not found", "success": ""},
                    status_code=401,
                )
        else:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Incorrect access code", "success": ""},
                status_code=401,
            )
    else:
        user = db.query(models.WorkspaceUser).filter_by(email=email).first()
        if not user or not workspace_auth.verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Incorrect email or password", "success": ""},
                status_code=401,
            )

    if user.status == "suspended":
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Your account has been suspended", "success": ""},
            status_code=403,
        )

    if user.status == "pending":
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Your account is pending approval", "success": ""},
            status_code=403,
        )

    cookie = workspace_auth.make_session_cookie(
        uid=user.id,
        email=user.email,
        role=user.role,
        name=user.full_name,
    )
    response = RedirectResponse(url="/copilot", status_code=303)
    response.set_cookie(
        workspace_auth.COOKIE_NAME,
        cookie,
        httponly=True,
        max_age=86400 * 30,
        samesite="lax",
        secure=True,
    )
    log.info("Login: %s role=%s", user.email, user.role)
    return response


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(workspace_auth.COOKIE_NAME)
    return response


# ── Invite acceptance ─────────────────────────────────────────────────────────

@router.get("/invite/{token}", response_class=HTMLResponse)
async def accept_invite_page(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    invite = _get_valid_invite(db, token)
    if invite is None:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "This invite link is invalid or has expired.",
                "success": "",
            },
        )
    return templates.TemplateResponse("accept_invite.html", {
        "request": request,
        "invite": invite,
        "token": token,
        "error": "",
    })


@router.post("/invite/{token}/accept")
async def accept_invite(
    request: Request,
    token: str,
    full_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    invite = _get_valid_invite(db, token)
    if invite is None:
        raise HTTPException(status_code=400, detail="Invite invalid or expired")

    full_name = full_name.strip()
    password  = password.strip()

    if len(password) < 8:
        return templates.TemplateResponse("accept_invite.html", {
            "request": request,
            "invite": invite,
            "token": token,
            "error": "Password must be at least 8 characters",
        })

    # Check email not already registered
    existing = db.query(models.WorkspaceUser).filter_by(email=invite.email).first()
    if existing:
        # Edge case: user already exists (invite accepted on another device)
        invite.used = True
        db.commit()
        return RedirectResponse("/login?success=Account+already+exists.+Please+log+in.", status_code=303)

    # Create the user
    user = models.WorkspaceUser(
        email=invite.email,
        full_name=full_name,
        role=invite.role,
        status="approved",
        password_hash=workspace_auth.hash_password(password),
    )
    db.add(user)
    invite.used = True
    db.commit()
    db.refresh(user)

    log.info("Invite accepted: %s role=%s", user.email, user.role)

    # Auto-login after acceptance
    cookie = workspace_auth.make_session_cookie(
        uid=user.id, email=user.email, role=user.role, name=user.full_name,
    )
    response = RedirectResponse(url="/copilot", status_code=303)
    response.set_cookie(
        workspace_auth.COOKIE_NAME, cookie,
        httponly=True, max_age=86400 * 30, samesite="lax", secure=True,
    )
    return response


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_valid_invite(db: Session, token: str):
    """Return the invite if it exists, is unused, and hasn't expired."""
    invite = db.query(models.WorkspaceInvite).filter_by(token=token, used=False).first()
    if not invite:
        return None
    if invite.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        return None
    return invite

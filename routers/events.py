"""
Event emitter — MyTodo → PHANG event bus.

MyTodo emits structured events to Gateway /internal/events.
PHANT reads these to build founder intelligence signals.

Phase 2 additions:
  MYTODO_USER_INVITED
  MYTODO_USER_APPROVED
  MYTODO_USER_SUSPENDED
  MYTODO_ROLE_CHANGED
"""

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("mytodo.events")

_GATEWAY_URL  = os.getenv("GATEWAY_URL", "https://api.infopro.ng")
_ADMIN_SECRET = os.getenv("PHANG_ADMIN_SECRET", "")


async def emit_event(event_type: str, payload: dict) -> None:
    """
    Fire-and-forget event emission to the Gateway event bus.
    Never raises — failures are logged and swallowed so they
    never block the user-facing request that triggered the event.
    """
    if not _ADMIN_SECRET:
        log.debug("[events] PHANG_ADMIN_SECRET not set — event %s not emitted", event_type)
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{_GATEWAY_URL}/internal/events",
                headers={"X-Admin-Secret": _ADMIN_SECRET},
                json={
                    "event":        event_type,
                    "service":      "mytodo",
                    "payload_json": payload,
                    "severity":     "info",
                },
            )
    except Exception as e:
        log.warning("[events] Failed to emit %s: %s", event_type, e)


# ── Phase 2: team lifecycle events ────────────────────────────────────────────

async def emit_user_invited(email: str, role: str, invited_by: str) -> None:
    await emit_event("MYTODO_USER_INVITED", {
        "email":      email,
        "role":       role,
        "invited_by": invited_by,
    })


async def emit_user_approved(email: str, role: str, approved_by: str) -> None:
    await emit_event("MYTODO_USER_APPROVED", {
        "email":       email,
        "role":        role,
        "approved_by": approved_by,
    })


async def emit_user_suspended(email: str, suspended_by: str) -> None:
    await emit_event("MYTODO_USER_SUSPENDED", {
        "email":        email,
        "suspended_by": suspended_by,
    })


async def emit_role_changed(
    email: str, old_role: str, new_role: str, changed_by: str
) -> None:
    await emit_event("MYTODO_ROLE_CHANGED", {
        "email":      email,
        "old_role":   old_role,
        "new_role":   new_role,
        "changed_by": changed_by,
    })

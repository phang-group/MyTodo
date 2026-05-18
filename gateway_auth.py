"""
MyTodo local auth — single-user internal tool.
Access code checked against MYTODO_ACCESS_CODE env var.
No gateway calls. Sets a signed session cookie.
"""
import hashlib
import hmac
import os
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

ACCESS_CODE   = os.getenv("MYTODO_ACCESS_CODE", "humble")
COOKIE_NAME   = "phang_token"
_SECRET       = os.getenv("MYTODO_COOKIE_SECRET", "mytodo-internal-secret")

# Fixed identity for the single owner — no gateway needed
_OWNER_IDENTITY = {
    "user_id": 1,
    "email":   os.getenv("MYTODO_OWNER_EMAIL", "admin@infopro.ng"),
    "name":    os.getenv("MYTODO_OWNER_NAME", "Boluwatife"),
    "valid":   True,
}


def _sign(value: str) -> str:
    return hmac.new(_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_cookie() -> str:
    payload = "authenticated"
    return f"{payload}.{_sign(payload)}"


def _verify_cookie(token: str) -> bool:
    try:
        payload, sig = token.rsplit(".", 1)
        return hmac.compare_digest(_sign(payload), sig) and payload == "authenticated"
    except Exception:
        return False


def check_access_code(code: str) -> bool:
    """Return True if code matches MYTODO_ACCESS_CODE."""
    return hmac.compare_digest(code.strip(), ACCESS_CODE)


def make_session_cookie() -> str:
    return _make_cookie()


async def get_current_identity(
    phang_token: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    if phang_token and _verify_cookie(phang_token):
        return _OWNER_IDENTITY
    return None


async def require_identity(
    identity: Optional[dict] = Depends(get_current_identity),
) -> dict:
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return identity

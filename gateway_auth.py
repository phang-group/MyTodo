"""
PHANG Shared Identity — gateway_auth.py (MyTodo)
All authentication delegates to the PHANG Go gateway.
No passwords, no JWTs issued here. This service verifies only.
"""
import os
from typing import Optional

import httpx
from fastapi import Cookie, Depends, HTTPException, status

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://app-gateway-1:8080")
PHANG_ADMIN_SECRET = os.getenv("PHANG_ADMIN_SECRET", "")
COOKIE_NAME = "phang_token"


async def _call_verify(token: str) -> Optional[dict]:
    """Hit gateway /api/auth/verify. Returns {user_id, email, name} or None."""
    if not token or not PHANG_ADMIN_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{GATEWAY_URL}/api/auth/verify",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Admin-Secret": PHANG_ADMIN_SECRET,
                },
            )
        if r.status_code == 200:
            data = r.json()
            return data if data.get("valid") else None
    except Exception:
        return None
    return None


async def _call_login(email: str, password: str) -> Optional[dict]:
    """Proxy login to gateway. Returns {access_token, ...} or None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{GATEWAY_URL}/api/auth/login",
                json={"email": email, "password": password},
            )
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None


async def _call_register(email: str, password: str, name: str) -> Optional[dict]:
    """Proxy registration to gateway. Returns {access_token, ...} or None.
    Raises ValueError('email_exists') on HTTP 409."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{GATEWAY_URL}/api/auth/register",
                json={"email": email, "password": password, "name": name},
            )
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 409:
            raise ValueError("email_exists")
    except ValueError:
        raise
    except Exception:
        return None
    return None


async def get_current_identity(
    phang_token: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """FastAPI dependency. Returns {user_id, email, name} or None."""
    return await _call_verify(phang_token)


async def require_identity(
    identity: Optional[dict] = Depends(get_current_identity),
) -> dict:
    """FastAPI dependency. Redirects to /login if not authenticated."""
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return identity

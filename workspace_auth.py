"""
workspace_auth.py — Multi-user auth for MyTodo Founder OS.

Phase 2 replaces the single-owner gateway_auth.py with a proper workspace
identity system. Sessions are HMAC-SHA256-signed blobs carrying:
  {uid, email, role, name, exp}

No JWT library. Uses Python stdlib: base64, hashlib, hmac, json.

Roles:   founder | coo | staff | viewer
Status:  approved | pending | suspended

Forward compat: when Gateway JWT is introduced, only sign_session() and
verify_session() change. All routers and permission checks are unchanged.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

COOKIE_NAME  = "phang_token"
SESSION_TTL  = 86400 * 30           # 30 days
_SECRET      = os.getenv("MYTODO_COOKIE_SECRET", "mytodo-internal-secret").strip()

ROLES_ORDERED = ("founder", "coo", "staff", "viewer")


# ── Password hashing (PBKDF2-SHA256, no external deps) ────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 with a random salt."""
    salt = os.urandom(16).hex()
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:260000:{salt}:{key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time password verification."""
    try:
        _, alg, iters, salt, stored_key = stored_hash.split(":", 4)
        key = hashlib.pbkdf2_hmac(alg, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(key.hex(), stored_key)
    except Exception:
        return False


# ── Session signing ────────────────────────────────────────────────────────────

def sign_session(uid: int, email: str, role: str, name: str) -> str:
    """
    Create a signed session token.
    Format: base64url(payload_json) + "." + hmac_sha256(base64url_part)
    """
    payload = {
        "uid":   uid,
        "email": email,
        "role":  role,
        "name":  name,
        "exp":   int(time.time()) + SESSION_TTL,
    }
    data = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_session(token: str) -> Optional[dict]:
    """
    Verify and decode a session token.
    Returns payload dict on success, None on any failure.
    Payload includes backward-compat alias: user_id = uid.
    """
    try:
        data, sig = token.rsplit(".", 1)
        expected  = hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        # Restore base64 padding
        pad    = 4 - len(data) % 4
        padded = data + "=" * (pad % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("exp", 0) < time.time():
            return None
        payload["valid"]   = True
        payload["user_id"] = payload["uid"]   # backward compat for existing routers
        return payload
    except Exception:
        return None


# ── FastAPI dependencies ────────────────────────────────────────────────────────

async def get_current_identity(
    phang_token: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """Returns identity dict or None if not authenticated / session invalid."""
    if not phang_token:
        return None
    return verify_session(phang_token)


async def require_identity(
    identity: Optional[dict] = Depends(get_current_identity),
) -> dict:
    """Require any authenticated session. Redirects to /login if absent."""
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return identity


def require_role(*roles: str):
    """
    Dependency factory: enforces that the authenticated user has one of the
    given roles. Returns 403 Access Denied otherwise.

    Usage:
        identity: dict = Depends(require_role("founder"))
        identity: dict = Depends(require_role("founder", "coo"))
    """
    async def _dep(identity: dict = Depends(require_identity)) -> dict:
        if identity.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        return identity
    return _dep


def make_session_cookie(uid: int, email: str, role: str, name: str) -> str:
    """Convenience wrapper — returns the cookie value string."""
    return sign_session(uid, email, role, name)

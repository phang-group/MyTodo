"""
gateway_auth.py — backward-compatibility adapter for workspace_auth.

Phase 2: All routers import from gateway_auth. This module re-exports
everything from workspace_auth so existing imports require no changes.

Phase 3 (Gateway JWT): workspace_auth.py sign_session / verify_session
will be swapped to Gateway JWT calls. This adapter stays unchanged.
"""
from workspace_auth import (  # noqa — full re-export
    COOKIE_NAME,
    hash_password,
    verify_password,
    sign_session,
    verify_session,
    get_current_identity,
    require_identity,
    require_role,
    make_session_cookie,
)

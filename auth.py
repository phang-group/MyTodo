# auth.py — compatibility shim
# All auth logic lives in gateway_auth.py
# This file preserved for any remaining import references.
from gateway_auth import get_current_identity, require_identity, COOKIE_NAME  # noqa: F401

"""JWT validation and claims helpers."""

from __future__ import annotations
from contextvars import ContextVar
from typing import Any

import jwt

from calllens.config import settings


# Claims stored per async-task (set by the HTTP middleware before each MCP call)
_current_claims: ContextVar[dict[str, Any]] = ContextVar(
    "mcp_claims",
    default={
        "sub": "anonymous",
        "tenant_id": str(settings.default_tenant_id),
        "role": "support_lead",
        "account_names": [],
    },
)


def set_claims(claims: dict[str, Any]) -> None:
    _current_claims.set(claims)


def get_claims() -> dict[str, Any]:
    return _current_claims.get()


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a HS256 JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def make_token(
    sub: str,
    role: str,
    account_names: list[str] | None = None,
    tenant_id: str | None = None,
    expires_in_hours: int = 24,
) -> str:
    """Generate a signed HS256 JWT — used by the token generator script."""
    import time
    payload = {
        "sub": sub,
        "tenant_id": tenant_id or str(settings.default_tenant_id),
        "role": role,
        "account_names": account_names or [],
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in_hours * 3600,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

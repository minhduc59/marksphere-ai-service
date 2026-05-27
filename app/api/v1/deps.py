"""Shared FastAPI dependencies for the v1 API.

These dependencies enforce the multi-user contract between the NestJS
backend gateway and the FastAPI ai-service:

1. `require_internal_auth` — rejects any request whose
   `X-Internal-Api-Key` header does not match `settings.INTERNAL_API_KEY`
   (when `REQUIRE_INTERNAL_AUTH` is enabled). The TikTok OAuth callback
   is the only public endpoint and opts out of this dependency.

2. `get_current_user_id` — reads the `X-User-Id` header set by NestJS
   after JWT validation and returns it as a UUID. Every user-scoped
   endpoint depends on this so that queries filter by the caller.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


async def require_internal_auth(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if not settings.REQUIRE_INTERNAL_AUTH:
        return
    if not settings.INTERNAL_API_KEY:
        return
    if x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API key",
        )


async def get_current_user_id(
    x_user_id: str | None = Header(default=None),
    _: None = Depends(require_internal_auth),
) -> uuid.UUID:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header — this endpoint must be called via the NestJS gateway",
        )
    try:
        return uuid.UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id header is not a valid UUID",
        ) from exc


async def get_optional_user_id(
    x_user_id: str | None = Header(default=None),
) -> uuid.UUID | None:
    """Same as `get_current_user_id` but does not raise when absent.

    Used by endpoints that must remain callable both by an authenticated
    user (scoped result) and by ai-service's own background jobs
    (global result).
    """
    if not x_user_id:
        return None
    try:
        return uuid.UUID(x_user_id)
    except ValueError:
        return None

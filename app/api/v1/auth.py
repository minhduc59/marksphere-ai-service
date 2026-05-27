"""TikTok OAuth endpoints — minimal flow for dev token acquisition."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.agents.publish_post.token_manager import save_tokens
from app.config import get_settings
from app.db.session import async_session_factory

logger = structlog.get_logger()
router = APIRouter()

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# In-memory CSRF state store (sufficient for single-user dev)
_csrf_states: set[str] = set()


@router.get(
    "/tiktok/login",
    summary="Start TikTok OAuth flow",
    description="Redirects to TikTok's authorization page. After user grants permission, TikTok redirects back to the callback URL.",
)
async def tiktok_login():
    """Generate the TikTok OAuth authorization URL and redirect."""
    settings = get_settings()

    if not settings.TIKTOK_CLIENT_KEY:
        raise HTTPException(
            status_code=500,
            detail="TIKTOK_CLIENT_KEY is not configured. Set it in .env.",
        )

    csrf_state = secrets.token_urlsafe(32)
    _csrf_states.add(csrf_state)

    params = {
        "client_key": settings.TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": "video.publish",
        "redirect_uri": settings.TIKTOK_REDIRECT_URI,
        "state": csrf_state,
    }

    auth_url = f"{TIKTOK_AUTH_URL}?{urlencode(params)}"
    logger.info("tiktok_oauth: redirecting to authorization", url=auth_url[:100])

    return RedirectResponse(url=auth_url)


@router.get(
    "/tiktok/callback",
    summary="TikTok OAuth callback",
    description="Receives the authorization code from TikTok, exchanges it for tokens, and stores them encrypted.",
)
async def tiktok_callback(
    code: str = Query(..., description="Authorization code from TikTok"),
    state: str = Query(..., description="CSRF state parameter"),
):
    """Exchange the authorization code for access + refresh tokens."""
    # Validate CSRF state
    if state not in _csrf_states:
        raise HTTPException(status_code=400, detail="Invalid state parameter (CSRF check failed)")
    _csrf_states.discard(state)

    settings = get_settings()

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.TIKTOK_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        logger.error("tiktok_oauth: token exchange HTTP error", status=response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"TikTok token exchange failed: HTTP {response.status_code}",
        )

    data = response.json()

    if "access_token" not in data:
        error = data.get("error", "unknown")
        error_desc = data.get("error_description", "")
        logger.error("tiktok_oauth: token exchange failed", error=error, desc=error_desc)
        raise HTTPException(
            status_code=502,
            detail=f"TikTok token exchange failed: {error} — {error_desc}",
        )

    # Store encrypted tokens
    async with async_session_factory() as db:
        token_row = await save_tokens(
            db=db,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data.get("expires_in", 86400),
            open_id=data.get("open_id", ""),
            scopes=data.get("scope", "").split(",") if data.get("scope") else ["video.publish"],
        )
        await db.commit()

    logger.info(
        "tiktok_oauth: tokens saved successfully",
        open_id=data.get("open_id"),
        expires_in=data.get("expires_in"),
    )

    return {
        "message": "TikTok authorization successful. Tokens saved.",
        "open_id": data.get("open_id"),
        "scopes": data.get("scope", "video.publish"),
    }

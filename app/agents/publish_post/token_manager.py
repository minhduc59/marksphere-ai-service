"""TikTok OAuth token encryption, storage, and automatic refresh."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import structlog
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ApiError
from app.db.models.user_platform_token import UserPlatformToken

logger = structlog.get_logger()

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


def _get_fernet() -> Fernet:
    settings = get_settings()
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string using Fernet (AES-128-CBC)."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted token string."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


async def save_tokens(
    db: AsyncSession,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    open_id: str,
    scopes: list[str] | None = None,
) -> UserPlatformToken:
    """Encrypt and upsert TikTok tokens into the database."""
    result = await db.execute(
        select(UserPlatformToken).where(UserPlatformToken.platform == "tiktok")
    )
    token_row = result.scalar_one_or_none()

    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    if token_row:
        token_row.access_token_encrypted = encrypted_access
        token_row.refresh_token_encrypted = encrypted_refresh
        token_row.token_expires_at = expires_at
        token_row.tiktok_open_id = open_id
        token_row.is_active = True
        if scopes:
            token_row.scopes = scopes
    else:
        token_row = UserPlatformToken(
            platform="tiktok",
            access_token_encrypted=encrypted_access,
            refresh_token_encrypted=encrypted_refresh,
            token_expires_at=expires_at,
            tiktok_open_id=open_id,
            scopes=scopes or ["video.publish"],
        )
        db.add(token_row)

    await db.flush()
    logger.info("tiktok_tokens: saved", open_id=open_id, expires_at=str(expires_at))
    return token_row


async def refresh_tiktok_token(refresh_token: str) -> dict:
    """Exchange a refresh token for new access + refresh tokens via TikTok OAuth."""
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        raise ApiError("tiktok", f"Token refresh failed: HTTP {response.status_code}", response.status_code)

    data = response.json()
    if "access_token" not in data:
        error = data.get("error", "unknown")
        error_desc = data.get("error_description", "")
        raise ApiError("tiktok", f"Token refresh failed: {error} — {error_desc}")

    logger.info("tiktok_tokens: refreshed", open_id=data.get("open_id"))
    return data


async def get_valid_token(db: AsyncSession) -> tuple[str, str]:
    """Get a valid TikTok access token, refreshing if expired.

    Returns:
        (access_token, open_id) tuple.

    Raises:
        ApiError: If no token exists or refresh fails.
    """
    result = await db.execute(
        select(UserPlatformToken).where(
            UserPlatformToken.platform == "tiktok",
            UserPlatformToken.is_active.is_(True),
        )
    )
    token_row = result.scalar_one_or_none()

    if not token_row:
        raise ApiError(
            "tiktok",
            "No TikTok token found. Authorize via GET /api/v1/auth/tiktok/login first.",
        )

    now = datetime.now(timezone.utc)

    # Refresh if token expires within the buffer window
    if token_row.token_expires_at < now + TOKEN_REFRESH_BUFFER:
        logger.info("tiktok_tokens: access token expiring, refreshing")
        refresh_tok = decrypt_token(token_row.refresh_token_encrypted)

        try:
            new_tokens = await refresh_tiktok_token(refresh_tok)
        except ApiError:
            # Refresh failed — mark token inactive so user re-authorizes
            token_row.is_active = False
            await db.flush()
            raise

        await save_tokens(
            db,
            access_token=new_tokens["access_token"],
            refresh_token=new_tokens["refresh_token"],
            expires_in=new_tokens["expires_in"],
            open_id=new_tokens.get("open_id", token_row.tiktok_open_id or ""),
            scopes=new_tokens.get("scope", "").split(",") if new_tokens.get("scope") else None,
        )

        return new_tokens["access_token"], new_tokens.get("open_id", token_row.tiktok_open_id or "")

    access_token = decrypt_token(token_row.access_token_encrypted)
    return access_token, token_row.tiktok_open_id or ""

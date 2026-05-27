"""Async TikTok Content Posting API client.

Handles: creator info query, photo post initialization, and publish status polling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

from app.config import get_settings
from app.core.exceptions import ApiError

logger = structlog.get_logger()

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

# Errors that should NOT be retried
NON_RETRYABLE_ERRORS = frozenset({
    "spam_risk_too_many_posts",
    "scope_not_authorized",
    "picture_size_check_failed",
    "token_not_authorized",
    "invalid_publish_id",
    "unaudited_client_can_only_post_to_private_accounts",
})


@dataclass
class CreatorInfo:
    """TikTok creator capabilities."""
    privacy_level_options: list[str]
    max_video_post_per_day: int
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool


@dataclass
class PublishResult:
    """Result from a TikTok publish operation."""
    publish_id: str
    status: str
    platform_post_id: str | None = None
    fail_reason: str | None = None


class TikTokClient:
    """Async client for TikTok Content Posting API."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def query_creator_info(self, access_token: str) -> CreatorInfo:
        """Query the creator's publishing capabilities and limits.

        See: https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info
        """
        url = f"{TIKTOK_API_BASE}/post/publish/creator_info/query/"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=self._headers(access_token))

        if response.status_code != 200:
            raise ApiError("tiktok", f"Creator info query failed: HTTP {response.status_code}", response.status_code)

        data = response.json()
        if data.get("error", {}).get("code") != "ok":
            error_msg = data.get("error", {}).get("message", "Unknown error")
            raise ApiError("tiktok", f"Creator info query failed: {error_msg}")

        info = data.get("data", {})
        logger.info(
            "tiktok: creator info fetched",
            privacy_options=info.get("privacy_level_options", []),
            max_posts=info.get("max_video_post_per_day"),
        )

        return CreatorInfo(
            privacy_level_options=info.get("privacy_level_options", []),
            max_video_post_per_day=info.get("max_video_post_per_day", 0),
            comment_disabled=info.get("comment_disabled", False),
            duet_disabled=info.get("duet_disabled", False),
            stitch_disabled=info.get("stitch_disabled", False),
        )

    async def init_photo_post(
        self,
        access_token: str,
        photo_urls: list[str],
        title: str,
        description: str,
        privacy_level: str = "SELF_ONLY",
        disable_comment: bool = False,
        auto_add_music: bool = True,
    ) -> str:
        """Initialize a direct photo post via PULL_FROM_URL.

        Returns the publish_id for status polling.

        See: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
        """
        url = f"{TIKTOK_API_BASE}/post/publish/content/init/"

        payload = {
            "post_info": {
                "title": title[:150],
                "description": description,
                "disable_comment": disable_comment,
                "privacy_level": privacy_level,
                "auto_add_music": auto_add_music,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 0,
                "photo_images": photo_urls,
            },
            "post_mode": "DIRECT_POST",
            "media_type": "PHOTO",
        }

        logger.info(
            "tiktok: initiating photo post",
            photo_count=len(photo_urls),
            privacy=privacy_level,
            title_len=len(title),
        )

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url, json=payload, headers=self._headers(access_token)
            )

        if response.status_code != 200:
            raise ApiError(
                "tiktok",
                f"Photo post init failed: HTTP {response.status_code} — {response.text}",
                response.status_code,
            )

        data = response.json()
        error_code = data.get("error", {}).get("code", "")
        if error_code != "ok":
            error_msg = data.get("error", {}).get("message", "Unknown error")
            logtype = data.get("error", {}).get("logid", "")
            raise ApiError("tiktok", f"Photo post init failed: {error_code} — {error_msg} (logid: {logtype})")

        publish_id = data.get("data", {}).get("publish_id", "")
        logger.info("tiktok: photo post initiated", publish_id=publish_id)
        return publish_id

    async def poll_publish_status(
        self,
        access_token: str,
        publish_id: str,
    ) -> PublishResult:
        """Poll TikTok for the publish status until terminal state.

        Polls at configured interval (default 10s) up to max attempts (default 30).
        """
        settings = self._settings
        url = f"{TIKTOK_API_BASE}/post/publish/status/fetch/"
        payload = {"publish_id": publish_id}

        for attempt in range(1, settings.PUBLISH_POLL_MAX_ATTEMPTS + 1):
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url, json=payload, headers=self._headers(access_token)
                )

            if response.status_code != 200:
                logger.warning(
                    "tiktok: status poll HTTP error",
                    publish_id=publish_id,
                    attempt=attempt,
                    status_code=response.status_code,
                )
                await asyncio.sleep(settings.PUBLISH_POLL_INTERVAL)
                continue

            data = response.json()
            status = data.get("data", {}).get("status", "PROCESSING_UPLOAD")

            logger.info(
                "tiktok: poll status",
                publish_id=publish_id,
                status=status,
                attempt=attempt,
            )

            if status == "PUBLISH_COMPLETE":
                post_id = data.get("data", {}).get("publicly_available_post_id", [])
                return PublishResult(
                    publish_id=publish_id,
                    status="PUBLISH_COMPLETE",
                    platform_post_id=post_id[0] if post_id else None,
                )

            if status == "FAILED":
                fail_reason = data.get("data", {}).get("fail_reason", "unknown")
                return PublishResult(
                    publish_id=publish_id,
                    status="FAILED",
                    fail_reason=fail_reason,
                )

            # Still processing — wait and retry
            await asyncio.sleep(settings.PUBLISH_POLL_INTERVAL)

        # Exhausted all poll attempts
        return PublishResult(
            publish_id=publish_id,
            status="FAILED",
            fail_reason="poll_timeout",
        )

    def is_retryable_error(self, fail_reason: str | None) -> bool:
        """Check if a TikTok publish failure is worth retrying."""
        if not fail_reason:
            return True
        return fail_reason not in NON_RETRYABLE_ERRORS


def get_tiktok_client() -> TikTokClient:
    """Return a TikTokClient instance."""
    return TikTokClient()

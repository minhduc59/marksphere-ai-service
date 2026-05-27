"""Cloudinary image uploader.

Single module that owns all Cloudinary interaction. Designed so the eventual
swap to S3 (or another provider) only edits this file — `image_generation.py`
and the publish pipeline talk to `upload_image_bytes` / `assert_cloudinary_url`
and never import the SDK directly.
"""

from __future__ import annotations

import asyncio
import io
import threading

import cloudinary
import cloudinary.uploader
import structlog

from app.config import get_settings

logger = structlog.get_logger()

_CONFIG_LOCK = threading.Lock()
_CONFIGURED = False


def _ensure_configured() -> None:
    """Lazily configure the Cloudinary SDK on first use.

    Raises RuntimeError with a clear message if any credential is missing —
    so a misconfigured environment fails loudly instead of silently saving
    to the wrong place.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    with _CONFIG_LOCK:
        if _CONFIGURED:
            return

        settings = get_settings()
        missing = [
            name
            for name, value in (
                ("CLOUDINARY_CLOUD_NAME", settings.CLOUDINARY_CLOUD_NAME),
                ("CLOUDINARY_API_KEY", settings.CLOUDINARY_API_KEY),
                ("CLOUDINARY_API_SECRET", settings.CLOUDINARY_API_SECRET),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Cloudinary is not configured — missing env vars: "
                + ", ".join(missing)
            )

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        _CONFIGURED = True


def assert_cloudinary_url(url: str | None) -> None:
    """Validate that a string is a public Cloudinary HTTPS URL.

    Used both right after upload (defence in depth) and at publish time
    (to refuse stale local-path values left in the DB before this fix).
    """
    if not url:
        raise ValueError("imageUrl is empty — expected a https://res.cloudinary.com URL")
    if not url.startswith("https://"):
        raise ValueError(
            f"imageUrl must start with https:// — got: {url[:80]}"
        )
    if "res.cloudinary.com" not in url:
        raise ValueError(
            f"imageUrl must be a Cloudinary URL (host res.cloudinary.com) — got: {url[:80]}"
        )


async def upload_image_bytes(
    data: bytes,
    *,
    public_id: str,
    content_type: str = "image/png",
) -> str:
    """Upload raw image bytes to Cloudinary and return the secure_url.

    Args:
        data: Raw image bytes from the generator (BFL / OpenAI gpt-image-1.5).
        public_id: Stable identifier used as the Cloudinary asset path,
            e.g. ``posts/<scan_run_id>/<post_id>``. The same value uploaded
            again will overwrite the previous version.
        content_type: MIME type — only used for logging; Cloudinary detects
            the actual format from the bytes.

    Returns:
        The ``secure_url`` returned by Cloudinary (validated to be a https
        URL on res.cloudinary.com).

    Raises:
        RuntimeError: if Cloudinary credentials are missing.
        ValueError: if the URL Cloudinary returned fails validation.
        cloudinary.exceptions.Error: on upload failure.
    """
    _ensure_configured()

    def _upload() -> dict:
        # Cloudinary's Python SDK is sync; we wrap it with asyncio.to_thread
        # so the LangGraph event loop stays unblocked while bytes upload.
        return cloudinary.uploader.upload(
            io.BytesIO(data),
            public_id=public_id,
            resource_type="image",
            overwrite=True,
            invalidate=True,
        )

    result = await asyncio.to_thread(_upload)
    secure_url = result.get("secure_url")
    assert_cloudinary_url(secure_url)
    logger.info(
        "cloudinary_uploader: uploaded",
        public_id=public_id,
        bytes=len(data),
        content_type=content_type,
        secure_url=secure_url,
    )
    return secure_url  # type: ignore[return-value]

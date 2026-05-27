"""OpenAI gpt-image-1.5.5 image generation client."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache

import structlog
from openai import AsyncOpenAI

from app.config import get_settings

logger = structlog.get_logger()

# OpenAI image API accepts these size strings
VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}


@dataclass
class ImageGenerationResult:
    """Result from an image generation request."""

    image_bytes: bytes
    content_type: str


class OpenAIImageClient:
    """Async client for OpenAI gpt-image-1.5 image generation."""

    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "high",
    ) -> ImageGenerationResult:
        """Generate an image using gpt-image-1.5. Returns raw image bytes."""
        if size not in VALID_SIZES:
            size = "1024x1024"

        logger.info(
            "openai_image: generating",
            prompt_len=len(prompt),
            size=size,
            quality=quality,
        )

        response = await self._client.images.generate(
            model="gpt-image-1.5",
            prompt=prompt,
            n=1,
            size=size,
            quality=quality,
        )

        # gpt-image-1.5 returns base64-encoded PNG by default
        b64_data = response.data[0].b64_json
        image_bytes = base64.b64decode(b64_data)

        logger.info("openai_image: generated", size_bytes=len(image_bytes))
        return ImageGenerationResult(
            image_bytes=image_bytes,
            content_type="image/png",
        )


@lru_cache
def get_image_client() -> OpenAIImageClient:
    """Return a cached OpenAIImageClient singleton."""
    settings = get_settings()
    return OpenAIImageClient(api_key=settings.OPENAI_API_KEY)

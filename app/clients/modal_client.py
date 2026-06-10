"""FLUX.2-klein LoRA image generation via Modal-deployed fine-tuned model."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import structlog

from app.config import get_settings

logger = structlog.get_logger()


@dataclass
class ImageGenerationResult:
    """Result from an image generation request."""

    image_bytes: bytes
    content_type: str


class ModalFluxClient:
    """Async client for the fine-tuned FLUX.2-klein model deployed on Modal."""

    def __init__(self, app_name: str, function_name: str, checkpoint: str) -> None:
        settings = get_settings()
        # Modal SDK reads auth from these env vars automatically.
        if settings.MODAL_TOKEN_ID:
            os.environ.setdefault("MODAL_TOKEN_ID", settings.MODAL_TOKEN_ID)
        if settings.MODAL_TOKEN_SECRET:
            os.environ.setdefault("MODAL_TOKEN_SECRET", settings.MODAL_TOKEN_SECRET)
        self._app_name = app_name
        self._function_name = function_name
        self._checkpoint = checkpoint

    async def generate_image(
        self,
        prompt: str,
        width: int = 768,
        height: int = 1344,
        seed: int = 0,
    ) -> ImageGenerationResult:
        """Call the Modal-deployed generate_finetuned function. Returns raw PNG bytes."""
        import modal  # imported here so modal SDK init happens after env vars are set

        logger.info(
            "modal_flux: generating",
            app=self._app_name,
            fn=self._function_name,
            checkpoint=self._checkpoint,
            width=width,
            height=height,
            prompt_len=len(prompt),
        )

        fn = modal.Function.from_name(self._app_name, self._function_name)
        image_bytes: bytes = await fn.remote.aio(
            prompt=prompt,
            seed=seed,
            checkpoint=self._checkpoint,
            lora_scale=1.0,
            width=width,
            height=height,
        )

        logger.info("modal_flux: generated", size_bytes=len(image_bytes))
        return ImageGenerationResult(image_bytes=image_bytes, content_type="image/png")


@lru_cache
def get_modal_client() -> ModalFluxClient:
    """Return a cached ModalFluxClient singleton."""
    settings = get_settings()
    return ModalFluxClient(
        app_name=settings.MODAL_APP_NAME,
        function_name=settings.MODAL_FUNCTION_NAME,
        checkpoint=settings.MODAL_CHECKPOINT,
    )

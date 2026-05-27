"""Step 2: Transcribe the source video with AssemblyAI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from app.clients import assemblyai_client
from app.config import get_settings

logger = structlog.get_logger()


def run(local_video_path: str) -> dict[str, Any]:
    """Transcribe the video. Returns {words, text, duration_ms}.

    Raises RuntimeError if ASSEMBLY_AI_API_KEY is not set or transcription fails.
    """
    settings = get_settings()
    if not settings.ASSEMBLY_AI_API_KEY:
        raise RuntimeError("ASSEMBLY_AI_API_KEY is not configured")

    logger.info("transcribe: starting", path=local_video_path)
    return assemblyai_client.transcribe(Path(local_video_path), settings.ASSEMBLY_AI_API_KEY)

"""AssemblyAI transcription client.

Ported from short-cut/supoclip/backend/src/video_utils.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

_AUDIO_EXTRACT_TIMEOUT_S = 900
_TRANSCRIPTION_MAX_RETRIES = 3


def extract_audio(video_path: Path) -> Path:
    """Extract compact mono 16kHz mp3 before uploading to AssemblyAI (cached)."""
    audio_path = video_path.with_name(f"{video_path.stem}.assemblyai.mp3")
    if audio_path.exists() and audio_path.stat().st_size > 0:
        return audio_path

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=_AUDIO_EXTRACT_TIMEOUT_S,
    )
    if result.returncode != 0 or not audio_path.exists() or audio_path.stat().st_size == 0:
        logger.warning("extract_audio: ffmpeg failed, using source video", stderr=result.stderr[-300:])
        return video_path

    logger.info(
        "extract_audio: done",
        path=str(audio_path),
        size_mb=round(audio_path.stat().st_size / 1_048_576, 2),
    )
    return audio_path


def transcribe(video_path: Path, api_key: str) -> dict[str, Any]:
    """Transcribe a video file with AssemblyAI word-level timestamps.

    Returns:
        {
            "words": [{"text": str, "start": int, "end": int, "confidence": float}],
            "text": str,
            "duration_ms": int,
        }

    Raises:
        RuntimeError on transcription failure after retries.
    """
    import assemblyai as aai

    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()
    config = aai.TranscriptionConfig(
        speaker_labels=False,
        punctuate=True,
        format_text=True,
        speech_models=["universal-2"],
    )

    audio_path = extract_audio(video_path)
    logger.info("transcribe: submitting to AssemblyAI", path=str(audio_path))

    transcript = None
    last_exc: Exception | None = None
    for attempt in range(1, _TRANSCRIPTION_MAX_RETRIES + 1):
        try:
            transcript = transcriber.transcribe(str(audio_path), config=config)
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("transcribe: attempt failed", attempt=attempt, error=str(exc))

    if transcript is None:
        raise RuntimeError(f"AssemblyAI transcription failed after {_TRANSCRIPTION_MAX_RETRIES} attempts: {last_exc}")

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI transcription error: {getattr(transcript, 'error', 'unknown')}")

    words = [
        {
            "text": w.text,
            "start": int(w.start),   # milliseconds
            "end": int(w.end),       # milliseconds
            "confidence": float(getattr(w, "confidence", 1.0) or 1.0),
        }
        for w in (transcript.words or [])
        if w.text and w.start is not None and w.end is not None
    ]

    duration_ms = words[-1]["end"] if words else 0
    logger.info(
        "transcribe: done",
        words=len(words),
        duration_s=round(duration_ms / 1000, 1),
    )
    return {
        "words": words,
        "text": transcript.text or "",
        "duration_ms": duration_ms,
    }

"""Step 5b: Extract a poster frame per final clip and upload it to Cloudinary.

Runs after caption.run (or directly after cut.run if subtitles are skipped),
before upload.run. Produces one JPEG per clip so the Clips Library page can
render a thumbnail without having to load the full video.

If frame extraction or upload fails for a given clip, that clip's
thumbnail entry is left as None — never blocks the pipeline.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

from app.core.storage import get_cloudinary_storage

logger = structlog.get_logger()

_FFMPEG_TIMEOUT_S = 60


def _extract_poster(clip_path: Path, duration_s: float, output_path: Path) -> bool:
    """Extract a single frame at 25% into the clip."""
    seek_s = max(0.5, duration_s * 0.25)
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{seek_s:.3f}",
            "-i", str(clip_path),
            "-vframes", "1",
            "-q:v", "3",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_S,
    )
    if result.returncode != 0:
        logger.warning(
            "thumbnail: ffmpeg poster extraction failed",
            clip=clip_path.name,
            stderr=result.stderr[-200:],
        )
        return False
    return True


def run(
    clip_local_paths: list[str],
    selected_segments: list[dict],
    task_temp_dir: str,
    task_id: str,
    user_id: str,
) -> list[dict | None]:
    """Generate and upload a poster image for each clip.

    Returns a list aligned with clip_local_paths; each entry is either
    {"url", "public_id"} or None if extraction/upload failed.
    """
    storage = get_cloudinary_storage()
    temp = Path(task_temp_dir)
    results: list[dict | None] = []

    for i, (clip_path_str, seg) in enumerate(zip(clip_local_paths, selected_segments)):
        clip_path = Path(clip_path_str)
        duration_s = (seg["end_ms"] - seg["start_ms"]) / 1000.0
        poster_path = temp / f"clip_{i:02d}_poster.jpg"

        if not _extract_poster(clip_path, duration_s, poster_path):
            results.append(None)
            continue

        try:
            dest_key = f"{user_id}/video-tasks/{task_id}/posters/clip_{i:02d}"
            obj = storage.upload_file(str(poster_path), dest_key, resource_type="image")
            results.append({"url": obj.url, "public_id": obj.public_id})
            logger.info("thumbnail: uploaded", index=i, public_id=obj.public_id)
        except Exception as exc:  # never fail the pipeline over a thumbnail
            logger.warning("thumbnail: upload failed", index=i, error=str(exc))
            results.append(None)

    return results

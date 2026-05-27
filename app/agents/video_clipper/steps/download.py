"""Step 1: Download or retrieve the source video file."""
from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger()

_FFMPEG_TIMEOUT_S = 600


def _download_youtube(url: str, output_path: Path) -> None:
    """Download a YouTube video using yt-dlp."""
    import yt_dlp  # optional dep — installed in worker container

    ydl_opts: dict = {
        # Write to the path without the extension; yt-dlp adds .mp4 automatically
        "outtmpl": str(output_path.with_suffix("")),
        "format": (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
            "/best[height<=1080][ext=mp4]"
            "/best[height<=1080]"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def _retrieve_upload(cloudinary_public_id: str, output_path: Path) -> None:
    """Download a previously uploaded video from Cloudinary."""
    from app.core.storage import get_cloudinary_storage

    storage = get_cloudinary_storage()
    storage.download_file(cloudinary_public_id, str(output_path))


def _trim_video(input_path: Path, output_path: Path, start_s: float, end_s: float) -> None:
    """Stream-copy trim [start_s, end_s] from input to output.

    end_s = 0 means no end limit (trim only the start).
    """
    args = ["ffmpeg", "-y"]
    if start_s > 0:
        args += ["-ss", str(start_s)]
    args += ["-i", str(input_path)]
    if end_s > 0:
        # -to is relative to the -ss offset
        args += ["-to", str(end_s - start_s)]
    args += ["-c", "copy", str(output_path)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_S)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg trim failed: {result.stderr[-500:]}")


def run(
    task_temp_dir: str,
    source_type: str,
    source_ref: str,
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
) -> str:
    """Download or retrieve the source video. Returns its local path.

    If start_time_s or end_time_s are set the video is trimmed immediately
    so subsequent steps (transcription, segment selection, cutting) operate
    on a smaller file that already starts at the user's chosen offset.
    """
    raw_path = Path(task_temp_dir) / "source_raw.mp4"
    output_path = Path(task_temp_dir) / "source.mp4"

    if source_type == "url":
        _download_youtube(source_ref, raw_path)
    elif source_type == "upload":
        _retrieve_upload(source_ref, raw_path)
    else:
        raise ValueError(f"Unknown source_type: {source_type!r}")

    if not raw_path.exists() or raw_path.stat().st_size == 0:
        raise RuntimeError(f"Video not found at {raw_path} after download")

    if start_time_s > 0 or end_time_s > 0:
        _trim_video(raw_path, output_path, start_time_s, end_time_s)
        raw_path.unlink(missing_ok=True)
        logger.info(
            "download: trimmed",
            start_s=start_time_s,
            end_s=end_time_s,
            size_mb=round(output_path.stat().st_size / 1_048_576, 2),
        )
    else:
        raw_path.rename(output_path)

    logger.info(
        "download: done",
        path=str(output_path),
        size_mb=round(output_path.stat().st_size / 1_048_576, 2),
    )
    return str(output_path)

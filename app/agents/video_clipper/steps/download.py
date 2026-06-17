"""Step 1: Download or retrieve the source video file."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()

_FFMPEG_TIMEOUT_S = 600

# RapidAPI host for resolving direct YouTube media URLs. YouTube blocks
# datacenter/AWS IPs, so this provider handles bot detection and we just
# stream the resulting URL ourselves. Subscribe to this exact API at
# https://rapidapi.com/ytjar/api/ytstream-download-youtube-videos
_RAPIDAPI_YT_HOST = "ytstream-download-youtube-videos.p.rapidapi.com"

# The provider mints media URLs for the ANDROID_VR client (visible as
# `c=ANDROID_VR` in the resolved googlevideo URL). YouTube returns 403 if the
# fetch User-Agent doesn't match the client the URL was signed for, so we stream
# the bytes with the matching Android VR UA.
_ANDROID_VR_UA = (
    "com.google.android.apps.youtube.vr.oculus/1.62.27 "
    "(Linux; U; Android 12; SM-G973F) gzip"
)

_YT_ID_RE = re.compile(r"(?:v=|/shorts/|/embed/|/v/|youtu\.be/)([A-Za-z0-9_-]{11})")


def _extract_video_id(url: str) -> str:
    """Pull the 11-char YouTube video id out of any common URL shape."""
    match = _YT_ID_RE.search(url)
    if not match:
        raise ValueError(f"Could not extract a YouTube video id from: {url!r}")
    return match.group(1)


def _resolve_mp4_candidates(video_id: str, settings) -> list[dict]:
    """Resolve progressive mp4 formats via RapidAPI, best quality first.

    Returns all progressive mp4 formats (prefer <=1080p) sorted highest-first,
    each with a fresh, signed `url`. Each call mints new short-lived media URLs,
    so we re-call this to recover from a 403 on the media fetch. ("formats" =
    progressive audio+video; "adaptiveFormats" = split tracks, which we skip so
    the pipeline needs no ffmpeg merge step.)
    """
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(
            f"https://{_RAPIDAPI_YT_HOST}/dl",
            params={"id": video_id},
            headers={
                "x-rapidapi-key": settings.RAPIDAPI_KEY,
                "x-rapidapi-host": _RAPIDAPI_YT_HOST,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "fail":
        raise RuntimeError(f"RapidAPI YouTube download failed: {data.get('msg') or data}")

    def _height(fmt: dict) -> int:
        return int(fmt.get("height") or 0)

    mp4s = [
        fmt for fmt in (data.get("formats") or [])
        if fmt.get("url") and "mp4" in (fmt.get("mimeType") or "")
    ]
    if not mp4s:
        raise RuntimeError("RapidAPI returned no progressive mp4 format for this video")

    candidates = [fmt for fmt in mp4s if _height(fmt) <= 1080] or mp4s
    return sorted(candidates, key=_height, reverse=True)


def _stream_media(media_url: str, output_path: Path) -> None:
    """Stream a googlevideo media URL to disk.

    Sends the Android VR client User-Agent (the provider mints URLs for that
    client) and a `Range: bytes=0-` header — googlevideo's progressive endpoint
    403s a plain GET for these client params, mirroring what the real Android
    client always sends. A 206 Partial Content response is a success here.

    Raises httpx.HTTPStatusError (e.g. 403) so the caller can try another format
    or re-resolve a fresh URL.
    """
    headers = {"User-Agent": _ANDROID_VR_UA, "Range": "bytes=0-"}
    with httpx.Client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", media_url, headers=headers) as media:
            media.raise_for_status()
            with open(output_path, "wb") as fh:
                for chunk in media.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)


def _download_youtube(url: str, output_path: Path) -> None:
    """Download a YouTube video via the RapidAPI ytstream downloader.

    YouTube blocks datacenter/AWS IPs directly, so we resolve a direct media
    URL through RapidAPI (the provider handles bot detection) and stream the
    file down ourselves. We pick a progressive mp4 (audio+video in one file),
    so the rest of the pipeline needs no ffmpeg merge step.

    The resolved googlevideo URLs are signed/short-lived and occasionally 403
    (expiry, client/IP-context mismatch). To recover we try every resolved mp4
    format in turn, then re-resolve a fresh batch of URLs once before giving up.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.RAPIDAPI_KEY:
        raise RuntimeError("RAPIDAPI_KEY is not configured — cannot download YouTube videos")

    video_id = _extract_video_id(url)

    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(2):
        candidates = _resolve_mp4_candidates(video_id, settings)
        for fmt in candidates:
            logger.info(
                "download: trying youtube media url",
                video_id=video_id,
                itag=fmt.get("itag"),
                quality=fmt.get("qualityLabel"),
                attempt=attempt,
            )
            try:
                _stream_media(fmt["url"], output_path)
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 403:
                    raise
                last_error = exc
                logger.warning(
                    "download: media url returned 403",
                    video_id=video_id,
                    itag=fmt.get("itag"),
                    attempt=attempt,
                )

    raise RuntimeError(
        f"YouTube media download failed with 403 after re-resolving for {video_id}"
    ) from last_error


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

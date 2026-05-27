"""Step 4: Cut segments and (optionally) reframe to 9:16 vertical with ffmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger()

_FFMPEG_TIMEOUT_S = 600


def _ffprobe_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-300:]}")
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def _cut_segment(video_path: Path, start_s: float, end_s: float, output_path: Path) -> None:
    """Fast stream-copy cut from source video."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{start_s:.3f}",
            "-to", f"{end_s:.3f}",
            "-i", str(video_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[-500:]}")


_RATIO_MAP = {
    "9:16": (9, 16, 1080, 1920),
    "16:9": (16, 9, 1920, 1080),
    "4:3":  (4,  3, 1440, 1080),
}


def _reframe(
    input_path: Path,
    output_path: Path,
    aspect_ratio: str = "9:16",
    crop_x: float = 0.5,
    crop_y: float = 0.5,
) -> None:
    """Crop and scale to the target aspect ratio using ffmpeg.

    crop_x / crop_y (0.0–1.0) set the crop-window centre within the source.
    0.5/0.5 is centre-crop; 0.0/0.0 is top-left.
    """
    src_w, src_h = _ffprobe_dimensions(input_path)

    ratio_w, ratio_h, out_w, out_h = _RATIO_MAP.get(aspect_ratio, _RATIO_MAP["9:16"])
    target_aspect = ratio_w / ratio_h
    src_aspect = src_w / src_h

    if abs(src_aspect - target_aspect) < 0.02:
        # Near-identical ratios: re-encode to standard resolution only
        shutil.copy(input_path, output_path)
        return

    if src_aspect > target_aspect:
        # Source is wider → crop width, keep full height
        frame_h = src_h
        frame_w = int(src_h * target_aspect)
        max_off_x = src_w - frame_w
        off_x = int(max_off_x * crop_x)
        off_y = 0
    else:
        # Source is taller → crop height, keep full width
        frame_w = src_w
        frame_h = int(src_w / target_aspect)
        max_off_y = src_h - frame_h
        off_x = 0
        off_y = int(max_off_y * crop_y)

    # libx264 requires even dimensions
    frame_w -= frame_w % 2
    frame_h -= frame_h % 2

    vf = (
        f"crop={frame_w}:{frame_h}:{off_x}:{off_y},"
        f"scale={out_w}:{out_h}:flags=lanczos,setsar=1"
    )

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg reframe failed: {result.stderr[-500:]}")


def run(
    local_video_path: str,
    task_temp_dir: str,
    selected_segments: list[dict],
    aspect_ratio: str = "9:16",
    crop_x: float = 0.5,
    crop_y: float = 0.5,
) -> tuple[list[str], list[str]]:
    """Cut all segments and statically reframe to the target aspect ratio.

    Returns (raw_paths, framed_paths) — both lists are 1:1 with ``selected_segments``.
    ``raw_paths`` are stream-copy cuts at the original 16:9; ``framed_paths`` are
    statically cropped/scaled to ``aspect_ratio``. A downstream smart-reframe step
    may consume ``raw_paths`` and replace entries in ``framed_paths``.

    aspect_ratio: "9:16" (default/TikTok), "16:9" (YouTube), "4:3" (classic).
    crop_x / crop_y: 0.0–1.0 crop-window centre within the source frame.
    """
    video_path = Path(local_video_path)
    temp = Path(task_temp_dir)
    raw_paths: list[str] = []
    framed_paths: list[str] = []

    for i, seg in enumerate(selected_segments):
        start_s = seg["start_ms"] / 1000.0
        end_s = seg["end_ms"] / 1000.0
        raw_path = temp / f"clip_{i:02d}_raw.mp4"
        framed_path = temp / f"clip_{i:02d}_framed.mp4"

        _cut_segment(video_path, start_s, end_s, raw_path)
        _reframe(raw_path, framed_path, aspect_ratio, crop_x, crop_y)
        raw_paths.append(str(raw_path))
        framed_paths.append(str(framed_path))
        logger.info(
            "cut: segment done",
            index=i,
            start_s=round(start_s, 2),
            end_s=round(end_s, 2),
            aspect_ratio=aspect_ratio,
        )

    return raw_paths, framed_paths

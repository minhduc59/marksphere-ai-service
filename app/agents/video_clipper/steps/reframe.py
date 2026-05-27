"""Step 4b: Optional smart subject-tracking reframe to 9:16.

When ``reframe_mode == "smart"`` and ``aspect_ratio == "9:16"``, runs the
vendored Autocrop-vertical CLI against each raw clip and replaces the
corresponding ``_framed.mp4`` with a ``_reframed.mp4`` driven by YOLOv8
subject detection. On any failure (timeout, non-zero exit, crash) the
original static ``_framed.mp4`` is kept so the pipeline never breaks for
a single clip.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ai-service/app/agents/video_clipper/steps/reframe.py
#   parents[0] = steps/
#   parents[1] = video_clipper/
#   parents[2] = agents/
#   parents[3] = app/
#   parents[4] = ai-service/  ← vendor lives here
_AUTOCROP_MAIN = Path(__file__).resolve().parents[4] / "vendor" / "autocrop_vertical" / "main.py"

_PER_CLIP_TIMEOUT_S = 300


def _run_autocrop(raw_path: str, reframed_path: Path) -> None:
    """Invoke vendored Autocrop-vertical. Raises on non-zero exit or timeout."""
    result = subprocess.run(
        [
            sys.executable,
            str(_AUTOCROP_MAIN),
            "-i", raw_path,
            "-o", str(reframed_path),
            "--ratio", "9:16",
            "--quality", "balanced",
        ],
        capture_output=True,
        text=True,
        timeout=_PER_CLIP_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"autocrop exit={result.returncode}: {result.stderr[-500:]}"
        )


def run(
    raw_paths: list[str],
    framed_paths: list[str],
    task_temp_dir: str,
    aspect_ratio: str,
    reframe_mode: str,
) -> list[str]:
    """Return the list of final framed paths after optional smart reframing.

    Fast no-op path: when smart reframing is not requested or the target
    aspect ratio is not 9:16, returns ``framed_paths`` unchanged.

    Smart path: for each raw clip, runs Autocrop-vertical and substitutes
    the reframed output. Per-clip failures fall back to the static frame.
    """
    if reframe_mode != "smart" or aspect_ratio != "9:16":
        return framed_paths

    if not _AUTOCROP_MAIN.is_file():
        logger.warning(
            "reframe: vendored main.py missing — falling back to static",
            expected_path=str(_AUTOCROP_MAIN),
        )
        return framed_paths

    temp = Path(task_temp_dir)
    final_paths: list[str] = []

    for i, (raw_path, framed_path) in enumerate(zip(raw_paths, framed_paths)):
        reframed_path = temp / f"clip_{i:02d}_reframed.mp4"
        started = time.monotonic()
        try:
            _run_autocrop(raw_path, reframed_path)
            duration_s = round(time.monotonic() - started, 2)
            final_paths.append(str(reframed_path))
            logger.info(
                "reframe: clip done",
                index=i,
                mode="smart",
                duration_s=duration_s,
            )
        except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
            duration_s = round(time.monotonic() - started, 2)
            stderr_tail = ""
            if isinstance(exc, subprocess.TimeoutExpired) and exc.stderr:
                stderr_tail = exc.stderr.decode("utf-8", errors="replace")[-500:]
            logger.warning(
                "reframe: clip failed, using static fallback",
                index=i,
                duration_s=duration_s,
                error=str(exc),
                stderr=stderr_tail,
            )
            final_paths.append(framed_path)

    return final_paths

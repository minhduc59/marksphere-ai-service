"""LangGraph state for the Video Clipper Agent pipeline."""
from __future__ import annotations

from typing import TypedDict


class VideoClipperState(TypedDict):
    # Input
    task_id: str
    user_id: str
    source_type: str         # "url" | "upload"
    source_ref: str          # YouTube URL or Cloudinary public_id
    font_id: str             # "" means use default
    caption_template_id: str  # "" means use default
    max_clips: int

    # Customization (one-time per task)
    caption_style: str        # "default" | "bold" | "minimal"
    aspect_ratio: str         # "9:16" | "16:9" | "4:3"
    crop_x: float             # 0.0–1.0 horizontal crop centre (0=left, 1=right)
    crop_y: float             # 0.0–1.0 vertical crop centre (0=top, 1=bottom)
    reframe_mode: str         # "static" (fixed crop_x/crop_y) | "smart" (Autocrop, 9:16 only)
    add_subtitles: bool       # False skips the caption burn step
    font_family: str          # bundled font key (Inter, Roboto, ...)
    font_size: int            # 12..48
    font_color: str           # "#RRGGBB"
    caption_position: str     # "top" | "center" | "bottom"

    # Time range — bracket the portion of the source video to analyze
    start_time_s: float       # seconds from start; 0 = beginning of video
    end_time_s: float         # seconds end limit; 0 = no limit (full video)

    # Runtime — set during execution
    task_temp_dir: str        # e.g. /tmp/marketing-video-clipper/{task_id}
    local_video_path: str     # local path after download / retrieval
    transcript_data: dict     # {words:[{text,start,end,confidence}], text:str, duration_ms:int}
    selected_segments: list[dict]  # [{start_ms,end_ms,text,score,rationale,virality:{...}}]
    clip_local_paths: list[str]    # per-clip final local paths (post-caption)
    clip_cloudinary_objects: list[dict]  # [{url,public_id}] per clip after upload

    # Output
    clip_ids: list[str]   # DB UUIDs of created VideoClip rows
    errors: list[str]

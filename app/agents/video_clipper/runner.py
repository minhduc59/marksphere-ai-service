"""Entry point for the Video Clipper Agent pipeline."""
from __future__ import annotations

import structlog

from app.agents.video_clipper.graph import build_video_clipper_graph
from app.agents.video_clipper.state import VideoClipperState

logger = structlog.get_logger()


async def run_video_clipper(
    task_id: str,
    user_id: str,
    source_type: str,
    source_ref: str,
    font_id: str = "",
    caption_template_id: str = "",
    max_clips: int = 5,
    caption_style: str = "default",
    aspect_ratio: str = "9:16",
    crop_x: float = 0.5,
    crop_y: float = 0.5,
    reframe_mode: str = "static",
    add_subtitles: bool = True,
    font_family: str = "Inter",
    font_size: int = 40,
    font_color: str = "#FFFFFF",
    caption_position: str = "bottom",
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
) -> dict:
    """Run the Video Clipper Agent pipeline.

    Customization fields (caption_style, aspect_ratio, crop_x, crop_y, add_subtitles,
    font_family, font_size, font_color, caption_position) are applied
    one-time for this task; they are also persisted on the VideoTask row
    so the rendered clips are traceable to their settings.

    Returns:
        {"task_id": str, "clip_ids": list[str], "error": str}
    """
    initial_state = VideoClipperState(
        task_id=task_id,
        user_id=user_id,
        source_type=source_type,
        source_ref=source_ref,
        font_id=font_id,
        caption_template_id=caption_template_id,
        max_clips=max_clips,
        caption_style=caption_style,
        aspect_ratio=aspect_ratio,
        crop_x=crop_x,
        crop_y=crop_y,
        reframe_mode=reframe_mode,
        add_subtitles=add_subtitles,
        font_family=font_family,
        font_size=font_size,
        font_color=font_color,
        caption_position=caption_position,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        task_temp_dir="",
        local_video_path="",
        transcript_data={},
        selected_segments=[],
        clip_local_paths=[],
        clip_cloudinary_objects=[],
        clip_ids=[],
        errors=[],
    )

    logger.info(
        "video_clipper: starting",
        task_id=task_id,
        source_type=source_type,
        max_clips=max_clips,
    )
    graph = build_video_clipper_graph()
    result = await graph.ainvoke(initial_state)

    clip_ids: list[str] = result.get("clip_ids", [])
    logger.info("video_clipper: finished", task_id=task_id, clip_count=len(clip_ids))

    return {
        "task_id": task_id,
        "clip_ids": clip_ids,
        "error": "",
    }

"""Step 5: Build ASS subtitle files and burn them into each clip with ffmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import structlog

from app.agents.video_clipper.fonts import FONT_CATALOG, FONTS_DIR, resolve_font

logger = structlog.get_logger()

_FFMPEG_TIMEOUT_S = 600
_WORDS_PER_GROUP = 3


# Caption style presets. Maps style key → (bold_flag, outline_width, shadow_depth)
#   bold_flag follows ASS convention: -1 = bold, 0 = normal
_STYLE_PRESETS: dict[str, tuple[int, int, int]] = {
    "default": (0, 2, 0),
    "bold":    (-1, 4, 0),
    "minimal": (0, 0, 1),
}


# caption_position → (Alignment, MarginV)
#   Alignment uses the ASS numpad layout: 8 = top-center, 5 = middle-center, 2 = bottom-center.
_POSITION_MAP: dict[str, tuple[int, int]] = {
    "top":    (8, 60),
    "center": (5, 0),
    "bottom": (2, 80),
}


def _ms_to_ass(ms: int) -> str:
    """Convert milliseconds to ASS timecode H:MM:SS.cc"""
    ms = max(0, ms)
    cs = (ms // 10) % 100
    total_s = ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB to ASS &H00BBGGRR (BGR order, 00 alpha = fully opaque)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}"


def _build_ass(
    words: list[dict],
    clip_start_ms: int,
    clip_end_ms: int,
    *,
    font_name: str,
    font_size: int,
    color: str,
    outline_color: str,
    style_key: str,
    position_key: str,
    play_res_x: int,
    play_res_y: int,
) -> str:
    """Build an ASS subtitle string from word timestamps, shifted to clip-relative time."""
    relevant = [
        w for w in words
        if w["start"] >= clip_start_ms and w["end"] <= clip_end_ms + 500
    ]

    ass_color = _hex_to_ass_color(color)
    ass_outline = _hex_to_ass_color(outline_color)

    bold_flag, outline_width, shadow = _STYLE_PRESETS.get(
        style_key, _STYLE_PRESETS["default"]
    )
    alignment, margin_v = _POSITION_MAP.get(position_key, _POSITION_MAP["bottom"])

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{ass_color},&H000000FF,"
        f"{ass_outline},&H00000000,"
        f"{bold_flag},0,0,0,100,100,0,0,1,{outline_width},{shadow},"
        f"{alignment},20,20,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    dialogue_lines: list[str] = []
    for i in range(0, len(relevant), _WORDS_PER_GROUP):
        group = relevant[i : i + _WORDS_PER_GROUP]
        start_ms = group[0]["start"] - clip_start_ms
        end_ms = group[-1]["end"] - clip_start_ms
        text = " ".join(w["text"] for w in group)
        dialogue_lines.append(
            f"Dialogue: 0,{_ms_to_ass(start_ms)},{_ms_to_ass(end_ms)},"
            f"Default,,0,0,0,,{text}"
        )

    return header + "\n".join(dialogue_lines)


def _ffmpeg_escape_path(path: str) -> str:
    """Escape a file path for use in an ffmpeg filtergraph value."""
    for char in ("\\", ":", "'"):
        path = path.replace(char, "\\" + char)
    return path


def _probe_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) — used to scale the ASS PlayRes to the clip size."""
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
        # Fall back to the vertical default; libass will scale anyway
        return 1080, 1920
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def run(
    framed_paths: list[str],
    task_temp_dir: str,
    selected_segments: list[dict],
    transcript_data: dict,
    *,
    font_family: str = "Inter",
    font_size: int = 40,
    font_color: str = "#FFFFFF",
    outline_color: str = "#000000",
    caption_style: str = "default",
    caption_position: str = "bottom",
) -> list[str]:
    """Burn ASS subtitles into each reframed clip. Returns list of captioned clip paths."""
    words: list[dict] = transcript_data.get("words", [])
    temp = Path(task_temp_dir)
    output_paths: list[str] = []

    font_path, ass_font_name = resolve_font(font_family)
    fonts_dir = font_path.parent if font_path.exists() else FONTS_DIR
    # Sanity: if the catalog is somehow empty (e.g. fontsdir missing), libass
    # will still render with a default sans-serif rather than crash.
    assert FONT_CATALOG, "font catalog must not be empty"

    for i, (framed_path, seg) in enumerate(zip(framed_paths, selected_segments)):
        clip_start_ms = seg["start_ms"]
        clip_end_ms = seg["end_ms"]
        ass_path = temp / f"clip_{i:02d}.ass"
        output_path = temp / f"clip_{i:02d}_final.mp4"

        # Match ASS PlayRes to actual clip dimensions so margins/font-size feel right
        # whether the clip is 9:16 vertical or kept-original wide-format.
        play_x, play_y = _probe_dimensions(Path(framed_path))

        ass_content = _build_ass(
            words,
            clip_start_ms,
            clip_end_ms,
            font_name=ass_font_name,
            font_size=font_size,
            color=font_color,
            outline_color=outline_color,
            style_key=caption_style,
            position_key=caption_position,
            play_res_x=play_x,
            play_res_y=play_y,
        )
        ass_path.write_text(ass_content, encoding="utf-8")

        subtitles_filter = (
            f"subtitles=filename={_ffmpeg_escape_path(str(ass_path))}"
            f":fontsdir={_ffmpeg_escape_path(str(fonts_dir))},setsar=1"
        )
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", framed_path,
                "-vf", subtitles_filter,
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
            # Caption burn failed — fall back to the framed clip without subtitles
            logger.warning(
                "caption: subtitle burn failed, using framed clip",
                index=i,
                stderr=result.stderr[-300:],
            )
            shutil.copy(framed_path, output_path)

        output_paths.append(str(output_path))
        logger.info(
            "caption: done",
            index=i,
            font=ass_font_name,
            style=caption_style,
            position=caption_position,
        )

    return output_paths

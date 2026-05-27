"""Assemble the final TikTok caption from post components."""

from __future__ import annotations

from app.agents.publish_post.constants import TIKTOK_CAPTION_MAX_CHARS


def assemble_caption(
    caption: str,
    hashtags: list[str],
    cta: str | None = None,
) -> str:
    """Build the full TikTok caption: caption body + hashtags + optional CTA.

    Enforces TikTok's 2200 character limit. If the assembled text exceeds the limit,
    the caption body is truncated (hashtags and CTA are always preserved).
    """
    # Normalize hashtags — ensure each starts with #
    normalized_tags = []
    for tag in hashtags:
        tag = tag.strip()
        if tag and not tag.startswith("#"):
            tag = f"#{tag}"
        if tag:
            normalized_tags.append(tag)

    hashtag_line = " ".join(normalized_tags)
    suffix_parts = [p for p in [hashtag_line, cta] if p]
    suffix = "\n\n".join(suffix_parts)

    # Reserve space for suffix + separator
    suffix_with_sep = f"\n\n{suffix}" if suffix else ""
    max_caption_len = TIKTOK_CAPTION_MAX_CHARS - len(suffix_with_sep)

    if len(caption) > max_caption_len:
        caption = caption[: max_caption_len - 3].rstrip() + "..."

    parts = [p for p in [caption, suffix] if p]
    return "\n\n".join(parts)

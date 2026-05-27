"""LangGraph state definition for the Publish Post Agent."""

from typing import TypedDict


class PublishPostState(TypedDict):
    # Input
    content_post_id: str
    user_id: str            # UUID of triggering user, "" if system/job
    publish_mode: str       # "auto" | "manual"
    scheduled_time_override: str   # ISO timestamp or "" for auto
    privacy_level: str      # TikTok privacy level passed through to publisher

    # Resolved during execution
    published_post_id: str  # DB record ID created at resolve_and_validate
    image_public_url: str
    assembled_caption: str

    # Scheduling
    golden_hour_result: dict   # GoldenHourResult as dict
    scheduled_at: str          # ISO UTC datetime chosen by scheduler, or "" for immediate

    # Publish results (set by publish_node)
    provider_post_id: str      # Publisher (Zernio) post ID returned by backend

    # Video branch — populated when content_type == "video"
    content_type: str   # "photo" | "video"; defaults to "photo" when not set
    video_url: str      # Cloudinary https URL for the clip; "" for photo posts

    # Final
    publish_status: str        # "processing" | "scheduled" | "failed"
    error: str

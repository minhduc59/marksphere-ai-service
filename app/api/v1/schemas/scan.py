import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.enums import Platform, ScanStatus


class PostGenOptions(BaseModel):
    num_posts: int = Field(default=3, ge=1, le=10, description="Number of posts to generate (1-10)")
    formats: list[str] | None = Field(
        default=None,
        description="Allowed post formats (e.g. quick_tips, hot_take, trending_breakdown). None = all.",
    )


class ScanOptions(BaseModel):
    max_items_per_platform: int = Field(default=50, ge=1, le=200, description="Max items to fetch (1–200)")
    include_comments: bool = Field(default=True, description="Whether to fetch top comments for each item")
    quality_threshold: int = Field(default=5, ge=1, le=10, description="Minimum quality score (1-10) to keep articles")
    keywords: list[str] = Field(
        default=[
            "Artificial Intelligence & Machine Learning",
            "Software Engineering & Developer Tools",
            "Cloud Computing & Infrastructure",
            "Cybersecurity & Privacy",
            "Open Source Projects",
            "Startups & Tech Industry",
            "Hardware & Semiconductors",
            "Programming Languages & Frameworks",
            "Data Science & Analytics",
            "Robotics & Automation",
        ],
        description="Target tech keywords for trend analysis",
    )
    generate_posts: bool = Field(
        default=True,
        description="Whether to auto-generate TikTok posts after scan completes",
    )
    post_gen_options: PostGenOptions = Field(
        default_factory=PostGenOptions,
        description="Options for post generation (only used when generate_posts=True)",
    )


class ScanRequest(BaseModel):
    platforms: list[Platform] = Field(
        default=[Platform.HACKERNEWS],
        description="Platforms to scan (currently only hackernews)",
    )
    options: ScanOptions = Field(default_factory=ScanOptions)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "platforms": ["hackernews"],
                    "options": {"max_items_per_platform": 30},
                },
                {
                    "platforms": ["hackernews"],
                    "options": {"max_items_per_platform": 50, "include_comments": False},
                },
                {
                    "platforms": ["hackernews"],
                    "options": {
                        "max_items_per_platform": 30,
                        "generate_posts": True,
                        "post_gen_options": {
                            "num_posts": 5,
                            "formats": ["quick_tips", "hot_take"],
                        },
                    },
                },
            ]
        }
    }


class ScanResponse(BaseModel):
    scan_id: uuid.UUID
    status: ScanStatus
    platforms: list[Platform]
    created_at: datetime


class ScanStatusResponse(BaseModel):
    scan_id: uuid.UUID
    status: ScanStatus
    platforms_completed: list[str] = []
    platforms_failed: dict[str, str] = {}
    total_items_found: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    current_step: str | None = None
    published_post_ids: list[str] = []
    source_type: str | None = None

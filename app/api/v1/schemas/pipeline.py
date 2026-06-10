from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PipelineConfigResponse(BaseModel):
    id: str
    owner_id: Optional[str]
    max_items_per_platform: int
    quality_threshold: int
    include_comments: bool
    keywords: list[str]
    num_posts: int
    allowed_formats: Optional[list[str]]
    require_review: bool
    auto_approve_threshold: float
    auto_publish: bool
    publish_mode: str
    scheduled_publish_time: Optional[str]
    default_privacy_level: str
    scan_schedule_enabled: bool
    scan_cron_expression: Optional[str]
    created_at: str
    updated_at: Optional[str]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: object) -> "PipelineConfigResponse":
        return cls(
            id=str(obj.id),  # type: ignore[attr-defined]
            owner_id=str(obj.owner_id) if obj.owner_id else None,  # type: ignore[attr-defined]
            max_items_per_platform=obj.max_items_per_platform,  # type: ignore[attr-defined]
            quality_threshold=obj.quality_threshold,  # type: ignore[attr-defined]
            include_comments=obj.include_comments,  # type: ignore[attr-defined]
            keywords=obj.keywords or [],  # type: ignore[attr-defined]
            num_posts=obj.num_posts,  # type: ignore[attr-defined]
            allowed_formats=obj.allowed_formats,  # type: ignore[attr-defined]
            require_review=obj.require_review,  # type: ignore[attr-defined]
            auto_approve_threshold=obj.auto_approve_threshold,  # type: ignore[attr-defined]
            auto_publish=obj.auto_publish,  # type: ignore[attr-defined]
            publish_mode=obj.publish_mode.value if hasattr(obj.publish_mode, "value") else str(obj.publish_mode),  # type: ignore[attr-defined]
            scheduled_publish_time=obj.scheduled_publish_time,  # type: ignore[attr-defined]
            default_privacy_level=obj.default_privacy_level,  # type: ignore[attr-defined]
            scan_schedule_enabled=obj.scan_schedule_enabled,  # type: ignore[attr-defined]
            scan_cron_expression=obj.scan_cron_expression,  # type: ignore[attr-defined]
            created_at=obj.created_at.isoformat() if obj.created_at else "",  # type: ignore[attr-defined]
            updated_at=obj.updated_at.isoformat() if obj.updated_at else None,  # type: ignore[attr-defined]
        )


class PipelineConfigUpdate(BaseModel):
    max_items_per_platform: Optional[int] = Field(default=None, ge=1, le=200)
    quality_threshold: Optional[int] = Field(default=None, ge=1, le=10)
    include_comments: Optional[bool] = None
    keywords: Optional[list[str]] = None
    num_posts: Optional[int] = Field(default=None, ge=1, le=10)
    allowed_formats: Optional[list[str]] = None
    require_review: Optional[bool] = None
    auto_approve_threshold: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    auto_publish: Optional[bool] = None
    publish_mode: Optional[str] = None
    scheduled_publish_time: Optional[str] = None
    default_privacy_level: Optional[str] = None
    scan_schedule_enabled: Optional[bool] = None
    scan_cron_expression: Optional[str] = None

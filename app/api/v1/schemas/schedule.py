import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.enums import Platform


class ScheduleRequest(BaseModel):
    cron_expression: str = Field(description="Cron expression, e.g. '0 */6 * * *' for every 6 hours")
    platforms: list[Platform] = Field(description="Platforms to include in the scheduled scan")
    is_active: bool = Field(default=True, description="Whether the schedule is active")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Every 6 hours — HackerNews scan",
                    "value": {
                        "cron_expression": "0 */6 * * *",
                        "platforms": ["hackernews"],
                        "is_active": True,
                    },
                },
                {
                    "summary": "Daily at 9am",
                    "value": {
                        "cron_expression": "0 9 * * *",
                        "platforms": ["hackernews"],
                        "is_active": True,
                    },
                },
            ]
        }
    }


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    cron_expression: str
    platforms: list[Platform]
    is_active: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

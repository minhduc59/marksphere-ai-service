"""add_pipeline_configs

Revision ID: 143e8f1d71e3
Revises: b1c2d3e4f5a6
Create Date: 2026-06-01 12:00:00.000000

Adds ai.pipeline_configs table for persisting per-user pipeline
configuration (review mode, auto-publish, scan schedule, etc.).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "143e8f1d71e3"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE ai.pipelinepublishmode AS ENUM ('auto', 'manual', 'schedule')"
    )
    op.execute(
        """
        CREATE TABLE ai.pipeline_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID,
            max_items_per_platform INTEGER NOT NULL DEFAULT 50,
            quality_threshold INTEGER NOT NULL DEFAULT 5,
            include_comments BOOLEAN NOT NULL DEFAULT TRUE,
            keywords JSONB NOT NULL DEFAULT '[]',
            num_posts INTEGER NOT NULL DEFAULT 3,
            allowed_formats JSONB,
            require_review BOOLEAN NOT NULL DEFAULT TRUE,
            auto_approve_threshold FLOAT NOT NULL DEFAULT 7.0,
            auto_publish BOOLEAN NOT NULL DEFAULT FALSE,
            publish_mode ai.pipelinepublishmode NOT NULL DEFAULT 'auto',
            scheduled_publish_time VARCHAR(5),
            default_privacy_level VARCHAR(50) NOT NULL DEFAULT 'SELF_ONLY',
            scan_schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            scan_cron_expression VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_pipeline_configs_owner_id ON ai.pipeline_configs(owner_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai.pipeline_configs")
    op.execute("DROP TYPE IF EXISTS ai.pipelinepublishmode")

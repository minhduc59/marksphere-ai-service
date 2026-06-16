"""add_hn_api_config_to_pipeline_configs

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-06-11 12:00:00.000000

Adds HackerNews API tuning columns to ai.pipeline_configs so the admin
Configuration page can persist the crawler rate limit and retry strategy.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai.pipeline_configs "
        "ADD COLUMN hn_rate_limit_per_min INTEGER NOT NULL DEFAULT 60"
    )
    op.execute(
        "ALTER TABLE ai.pipeline_configs "
        "ADD COLUMN hn_retry_strategy VARCHAR(20) NOT NULL DEFAULT 'exponential'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ai.pipeline_configs DROP COLUMN IF EXISTS hn_retry_strategy")
    op.execute("ALTER TABLE ai.pipeline_configs DROP COLUMN IF EXISTS hn_rate_limit_per_min")

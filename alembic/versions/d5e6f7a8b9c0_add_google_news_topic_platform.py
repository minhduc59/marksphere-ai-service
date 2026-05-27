"""add_google_news_topic_platform

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-03-29 20:00:00.000000

Add 'google_news_topic' value to the platform enum for topic-based news scanning.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'google_news_topic'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # Recreate the enum without 'google_news_topic'.
    op.execute("DROP INDEX IF EXISTS ix_trend_items_platform_category")
    op.execute("ALTER TABLE trend_items ALTER COLUMN platform TYPE VARCHAR USING platform::text")
    op.execute("DELETE FROM trend_items WHERE platform = 'google_news_topic'")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute("CREATE TYPE platform AS ENUM ('youtube', 'google_news')")
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN platform TYPE platform "
        "USING platform::platform"
    )
    op.execute(
        "CREATE INDEX ix_trend_items_platform_category "
        "ON trend_items (platform, category)"
    )

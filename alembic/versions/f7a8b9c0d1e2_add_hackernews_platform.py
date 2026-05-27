"""add_hackernews_platform

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-01 12:00:00.000000

Add 'hackernews' value to the platform enum for Hacker News scanning.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'hackernews'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    op.execute("DROP INDEX IF EXISTS ix_trend_items_platform_category")
    op.execute("ALTER TABLE trend_items ALTER COLUMN platform TYPE VARCHAR USING platform::text")
    op.execute("DELETE FROM trend_items WHERE platform = 'hackernews'")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute(
        "CREATE TYPE platform AS ENUM "
        "('youtube', 'google_news', 'google_news_topic', 'google_news_category')"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN platform TYPE platform "
        "USING platform::platform"
    )
    op.execute(
        "CREATE INDEX ix_trend_items_platform_category "
        "ON trend_items (platform, category)"
    )

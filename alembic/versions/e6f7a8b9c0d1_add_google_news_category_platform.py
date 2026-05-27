"""add_google_news_category_platform

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-31 12:00:00.000000

Add 'google_news_category' value to the platform enum for category-based news scanning.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'google_news_category'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # Recreate the enum without 'google_news_category'.
    op.execute("DROP INDEX IF EXISTS ix_trend_items_platform_category")
    op.execute("ALTER TABLE trend_items ALTER COLUMN platform TYPE VARCHAR USING platform::text")
    op.execute("DELETE FROM trend_items WHERE platform = 'google_news_category'")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute("CREATE TYPE platform AS ENUM ('youtube', 'google_news', 'google_news_topic')")
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN platform TYPE platform "
        "USING platform::platform"
    )
    op.execute(
        "CREATE INDEX ix_trend_items_platform_category "
        "ON trend_items (platform, category)"
    )

"""upgrade_analysis_fields

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-01 14:00:00.000000

Add new analysis fields to trend_items and update sentiment/lifecycle enums
for the combined trend analyzer + report generation pipeline.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Update sentiment enum: positive/negative/neutral/mixed → bullish/neutral/bearish/controversial ---
    # Convert ALL columns using this enum to text first (trend_items + trend_comments)
    # Use LOWER() because PostgreSQL may store enum values in uppercase
    op.execute("ALTER TABLE trend_items ALTER COLUMN sentiment TYPE VARCHAR USING LOWER(sentiment::text)")
    op.execute("ALTER TABLE trend_comments ALTER COLUMN sentiment TYPE VARCHAR USING LOWER(sentiment::text)")
    op.execute("DROP TYPE IF EXISTS sentiment")
    # Map old values to new: positive→bullish, negative→bearish, mixed→controversial, neutral stays
    op.execute(
        "UPDATE trend_items SET sentiment = CASE sentiment "
        "WHEN 'positive' THEN 'bullish' "
        "WHEN 'negative' THEN 'bearish' "
        "WHEN 'mixed' THEN 'controversial' "
        "ELSE 'neutral' END "
        "WHERE sentiment IS NOT NULL"
    )
    op.execute(
        "UPDATE trend_comments SET sentiment = CASE sentiment "
        "WHEN 'positive' THEN 'bullish' "
        "WHEN 'negative' THEN 'bearish' "
        "WHEN 'mixed' THEN 'controversial' "
        "ELSE 'neutral' END "
        "WHERE sentiment IS NOT NULL"
    )
    op.execute(
        "CREATE TYPE sentiment AS ENUM ('bullish', 'neutral', 'bearish', 'controversial')"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN sentiment TYPE sentiment "
        "USING sentiment::sentiment"
    )
    op.execute(
        "ALTER TABLE trend_comments ALTER COLUMN sentiment TYPE sentiment "
        "USING sentiment::sentiment"
    )

    # --- Update trendlifecycle enum: rising/peak/declining → emerging/rising/peaking/saturated/declining ---
    # Convert column to text first, LOWER() for safety
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN lifecycle TYPE VARCHAR USING LOWER(lifecycle::text)"
    )
    op.execute("DROP TYPE IF EXISTS trendlifecycle")
    # Map old values: peak→peaking, rising/declining stay
    op.execute(
        "UPDATE trend_items SET lifecycle = CASE lifecycle "
        "WHEN 'peak' THEN 'peaking' "
        "ELSE lifecycle END "
        "WHERE lifecycle IS NOT NULL"
    )
    op.execute(
        "CREATE TYPE trendlifecycle AS ENUM "
        "('emerging', 'rising', 'peaking', 'saturated', 'declining')"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN lifecycle TYPE trendlifecycle "
        "USING lifecycle::trendlifecycle"
    )

    # --- Create new enum types ---
    op.execute(
        "CREATE TYPE engagementprediction AS ENUM ('low', 'medium', 'high', 'viral')"
    )
    op.execute(
        "CREATE TYPE sourcetype AS ENUM "
        "('official_blog', 'news', 'research', 'community', 'social')"
    )

    # --- Add new columns ---
    op.add_column(
        "trend_items",
        sa.Column("quality_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "trend_items",
        sa.Column(
            "engagement_prediction",
            sa.Enum(
                "low", "medium", "high", "viral",
                name="engagementprediction",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "trend_items",
        sa.Column(
            "source_type",
            sa.Enum(
                "official_blog", "news", "research", "community", "social",
                name="sourcetype",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "trend_items",
        sa.Column("linkedin_angles", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "trend_items",
        sa.Column("key_data_points", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "trend_items",
        sa.Column("target_audience", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "trend_items",
        sa.Column("cleaned_content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Drop new columns
    op.drop_column("trend_items", "cleaned_content")
    op.drop_column("trend_items", "target_audience")
    op.drop_column("trend_items", "key_data_points")
    op.drop_column("trend_items", "linkedin_angles")
    op.drop_column("trend_items", "source_type")
    op.drop_column("trend_items", "engagement_prediction")
    op.drop_column("trend_items", "quality_score")

    # Drop new enum types
    op.execute("DROP TYPE IF EXISTS sourcetype")
    op.execute("DROP TYPE IF EXISTS engagementprediction")

    # Revert trendlifecycle enum
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN lifecycle TYPE VARCHAR USING LOWER(lifecycle::text)"
    )
    op.execute("DROP TYPE IF EXISTS trendlifecycle")
    op.execute(
        "UPDATE trend_items SET lifecycle = CASE lifecycle "
        "WHEN 'emerging' THEN 'rising' "
        "WHEN 'peaking' THEN 'peak' "
        "WHEN 'saturated' THEN 'declining' "
        "ELSE lifecycle END "
        "WHERE lifecycle IS NOT NULL"
    )
    op.execute(
        "CREATE TYPE trendlifecycle AS ENUM ('rising', 'peak', 'declining')"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN lifecycle TYPE trendlifecycle "
        "USING lifecycle::trendlifecycle"
    )

    # Revert sentiment enum (both trend_items and trend_comments use it)
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN sentiment TYPE VARCHAR USING LOWER(sentiment::text)"
    )
    op.execute(
        "ALTER TABLE trend_comments ALTER COLUMN sentiment TYPE VARCHAR USING LOWER(sentiment::text)"
    )
    op.execute("DROP TYPE IF EXISTS sentiment")
    op.execute(
        "UPDATE trend_items SET sentiment = CASE sentiment "
        "WHEN 'bullish' THEN 'positive' "
        "WHEN 'bearish' THEN 'negative' "
        "WHEN 'controversial' THEN 'mixed' "
        "ELSE 'neutral' END "
        "WHERE sentiment IS NOT NULL"
    )
    op.execute(
        "UPDATE trend_comments SET sentiment = CASE sentiment "
        "WHEN 'bullish' THEN 'positive' "
        "WHEN 'bearish' THEN 'negative' "
        "WHEN 'controversial' THEN 'mixed' "
        "ELSE 'neutral' END "
        "WHERE sentiment IS NOT NULL"
    )
    op.execute(
        "CREATE TYPE sentiment AS ENUM ('positive', 'negative', 'neutral', 'mixed')"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN sentiment TYPE sentiment "
        "USING sentiment::sentiment"
    )
    op.execute(
        "ALTER TABLE trend_comments ALTER COLUMN sentiment TYPE sentiment "
        "USING sentiment::sentiment"
    )

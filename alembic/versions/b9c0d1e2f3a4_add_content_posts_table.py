"""add_content_posts_table

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-04-02 10:00:00.000000

Add content_posts table for storing generated LinkedIn posts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely create enum types (idempotent via exception handling)
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE contentstatus AS ENUM "
        "('draft', 'approved', 'needs_revision', 'flagged_for_review', 'published'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE postformat AS ENUM "
        "('thought_leadership', 'hot_take', 'case_study', 'tutorial', "
        "'industry_analysis', 'career_advice', 'behind_the_scenes'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    ))

    # Use postgresql.ENUM with create_type=False to reference existing types
    # without SQLAlchemy trying to auto-create them
    contentstatus_col = postgresql.ENUM(
        "draft", "approved", "needs_revision", "flagged_for_review", "published",
        name="contentstatus", create_type=False,
    )
    postformat_col = postgresql.ENUM(
        "thought_leadership", "hot_take", "case_study", "tutorial",
        "industry_analysis", "career_advice", "behind_the_scenes",
        name="postformat", create_type=False,
    )

    op.create_table(
        "content_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scan_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scan_runs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "trend_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trend_items.id"),
            nullable=True,
        ),
        # Content
        sa.Column("format", postformat_col, nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("hashtags", sa.JSON, server_default="[]"),
        sa.Column("cta", sa.String, nullable=True),
        sa.Column("image_prompt", sa.JSON, nullable=True),
        # Source
        sa.Column("trend_title", sa.String(500), nullable=False),
        sa.Column("trend_url", sa.String, nullable=True),
        sa.Column("linkedin_angle_used", sa.String, nullable=True),
        sa.Column("target_audience", sa.JSON, server_default="[]"),
        # Posting metadata
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("estimated_read_time", sa.String(50), nullable=True),
        sa.Column("engagement_prediction", sa.String(20), nullable=True),
        sa.Column("best_posting_day", sa.String(20), nullable=True),
        sa.Column("best_posting_time", sa.String(30), nullable=True),
        sa.Column("timing_window", sa.String(100), nullable=True),
        # Review
        sa.Column("status", contentstatus_col, server_default="draft"),
        sa.Column("review_score", sa.Float, nullable=True),
        sa.Column("review_notes", sa.Text, nullable=True),
        sa.Column("review_criteria", sa.JSON, nullable=True),
        sa.Column("revision_count", sa.Integer, server_default="0"),
        # File
        sa.Column("file_path", sa.String, nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("content_posts")
    op.execute(sa.text("DROP TYPE IF EXISTS postformat"))
    op.execute(sa.text("DROP TYPE IF EXISTS contentstatus"))

"""add_publish_tables

Revision ID: e1f2a3b4c5d6
Revises: d6e7f8a9b0c1
Create Date: 2026-04-10 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values for new types
publish_status_values = ("pending", "processing", "published", "failed", "cancelled")
publish_mode_values = ("auto", "manual")


def upgrade() -> None:
    # Create enum types
    publish_status_enum = sa.Enum(
        *publish_status_values, name="publishstatus", create_type=True
    )
    publish_mode_enum = sa.Enum(
        *publish_mode_values, name="publishmode", create_type=True
    )

    # --- user_platform_tokens ---
    op.create_table(
        "user_platform_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(20), nullable=False, server_default="tiktok"),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tiktok_open_id", sa.String(), nullable=True),
        sa.Column("scopes", sa.JSON(), server_default="[]"),
        sa.Column("creator_info_cache", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- published_posts ---
    op.create_table(
        "published_posts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("content_post_id", UUID(as_uuid=True), sa.ForeignKey("content_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False, server_default="tiktok"),
        sa.Column("publish_mode", publish_mode_enum, nullable=False),
        sa.Column("status", publish_status_enum, server_default="pending"),
        sa.Column("privacy_level", sa.String(50), server_default="SELF_ONLY"),
        sa.Column("tiktok_publish_id", sa.String(255), nullable=True),
        sa.Column("platform_post_id", sa.String(255), nullable=True),
        sa.Column("golden_hour_slot", sa.String(11), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduler_job_id", sa.String(100), nullable=True),
        sa.Column("assembled_caption", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("api_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_published_posts_content_post", "published_posts", ["content_post_id"])
    op.create_index("idx_published_posts_status", "published_posts", ["status"])

    # --- engagement_time_slots ---
    op.create_table(
        "engagement_time_slots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(20), nullable=False, server_default="tiktok"),
        sa.Column("time_slot", sa.String(11), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("avg_views", sa.Float(), server_default="0"),
        sa.Column("avg_likes", sa.Float(), server_default="0"),
        sa.Column("avg_comments", sa.Float(), server_default="0"),
        sa.Column("avg_shares", sa.Float(), server_default="0"),
        sa.Column("weighted_score", sa.Float(), server_default="0"),
        sa.Column("sample_count", sa.Integer(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_platform_slot_index", "engagement_time_slots", ["platform", "slot_index"]
    )


def downgrade() -> None:
    op.drop_table("engagement_time_slots")
    op.drop_table("published_posts")
    op.drop_table("user_platform_tokens")

    # Drop enum types
    sa.Enum(name="publishstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="publishmode").drop(op.get_bind(), checkfirst=True)

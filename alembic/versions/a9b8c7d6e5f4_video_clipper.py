"""video_clipper: add content_type to content_posts + new video tables

Revision ID: a9b8c7d6e5f4
Revises: d1e2f3a4b5c6
Create Date: 2026-05-13 12:00:00.000000

Non-destructive changes:
1. Add ai.content_posts.content_type column — VARCHAR(10) NOT NULL DEFAULT 'photo'.
   All existing rows immediately satisfy the constraint via the server default.
2. Create ai.brand_fonts
3. Create ai.caption_templates
4. Create ai.video_tasks (FK → brand_fonts, caption_templates, scan_runs)
5. Create ai.video_clips (FK → video_tasks, content_posts, published_posts)

Status columns on video_tasks and video_clips use VARCHAR (not PG enum types)
so that new status values can be added without requiring an ALTER TYPE migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Extend content_posts with a content_type discriminator column    #
    # ------------------------------------------------------------------ #
    op.add_column(
        "content_posts",
        sa.Column(
            "content_type",
            sa.String(10),
            nullable=False,
            server_default="photo",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_content_posts_content_type",
        "content_posts",
        ["content_type"],
        schema="ai",
    )

    # ------------------------------------------------------------------ #
    # 2. brand_fonts                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "brand_fonts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("storage_public_id", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        schema="ai",
    )
    op.create_index("ix_ai_brand_fonts_user_id", "brand_fonts", ["user_id"], schema="ai")

    # ------------------------------------------------------------------ #
    # 3. caption_templates                                                 #
    # ------------------------------------------------------------------ #
    op.create_table(
        "caption_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("font_size", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("color", sa.String(20), nullable=False, server_default="#FFFFFF"),
        sa.Column("outline_color", sa.String(20), nullable=False, server_default="#000000"),
        sa.Column("outline_width", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("vertical_position", sa.String(20), nullable=False, server_default="bottom"),
        sa.Column("style_payload", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_caption_templates_user_id", "caption_templates", ["user_id"], schema="ai"
    )

    # ------------------------------------------------------------------ #
    # 4. video_tasks                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "video_tasks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column(
            "font_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.brand_fonts.id"),
            nullable=True,
        ),
        sa.Column(
            "caption_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.caption_templates.id"),
            nullable=True,
        ),
        sa.Column("max_clips", sa.SmallInteger(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("temp_dir", sa.Text(), nullable=True),
        sa.Column(
            "scan_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.scan_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="ai",
    )
    op.create_index("ix_ai_video_tasks_user_id", "video_tasks", ["user_id"], schema="ai")
    op.create_index("ix_ai_video_tasks_status", "video_tasks", ["status"], schema="ai")
    op.create_index(
        "ix_ai_video_tasks_created_at", "video_tasks", ["created_at"], schema="ai"
    )

    # ------------------------------------------------------------------ #
    # 5. video_clips                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "video_clips",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_post_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.content_posts.id"),
            nullable=True,
        ),
        sa.Column("clip_index", sa.Integer(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("storage_public_id", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("transcript_segment", sa.Text(), nullable=True),
        sa.Column("llm_score", sa.Float(), nullable=True),
        sa.Column("llm_rationale", sa.Text(), nullable=True),
        sa.Column("hook_score", sa.Float(), nullable=True),
        sa.Column("engagement_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("platform_post_id", sa.Text(), nullable=True),
        sa.Column(
            "published_post_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai.published_posts.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="ai",
    )
    op.create_index("ix_ai_video_clips_task_id", "video_clips", ["task_id"], schema="ai")
    op.create_index(
        "ix_ai_video_clips_content_post_id", "video_clips", ["content_post_id"], schema="ai"
    )
    op.create_index("ix_ai_video_clips_status", "video_clips", ["status"], schema="ai")
    # One ContentPost can link to at most one VideoClip
    op.create_unique_constraint(
        "uq_video_clips_content_post_id", "video_clips", ["content_post_id"], schema="ai"
    )


def downgrade() -> None:
    op.drop_constraint("uq_video_clips_content_post_id", "video_clips", schema="ai", type_="unique")
    op.drop_table("video_clips", schema="ai")

    op.drop_index("ix_ai_video_tasks_created_at", "video_tasks", schema="ai")
    op.drop_index("ix_ai_video_tasks_status", "video_tasks", schema="ai")
    op.drop_index("ix_ai_video_tasks_user_id", "video_tasks", schema="ai")
    op.drop_table("video_tasks", schema="ai")

    op.drop_index("ix_ai_caption_templates_user_id", "caption_templates", schema="ai")
    op.drop_table("caption_templates", schema="ai")

    op.drop_index("ix_ai_brand_fonts_user_id", "brand_fonts", schema="ai")
    op.drop_table("brand_fonts", schema="ai")

    op.drop_index("ix_ai_content_posts_content_type", "content_posts", schema="ai")
    op.drop_column("content_posts", "content_type", schema="ai")

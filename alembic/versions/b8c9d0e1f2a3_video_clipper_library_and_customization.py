"""video_clipper: clips library (thumbnails, title) + per-task customization

Revision ID: b8c9d0e1f2a3
Revises: a9b8c7d6e5f4
Create Date: 2026-05-15 12:00:00.000000

Adds:
1. ai.video_clips.thumbnail_url, thumbnail_public_id, title — to power the
   Clips Library page.
2. ai.video_tasks: 7 customization columns (caption_style, wide_format,
   add_subtitles, font_family, font_size, font_color, caption_position)
   so each task records the settings it was rendered with.

All new columns are nullable or have safe server defaults, so existing rows
are unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # video_clips: thumbnail + title
    op.add_column(
        "video_clips",
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "video_clips",
        sa.Column("thumbnail_public_id", sa.Text(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "video_clips",
        sa.Column("title", sa.String(120), nullable=True),
        schema="ai",
    )

    # video_tasks: customization columns
    op.add_column(
        "video_tasks",
        sa.Column(
            "caption_style", sa.String(20), nullable=False, server_default="default"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "wide_format", sa.Boolean(), nullable=False, server_default="false"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "add_subtitles", sa.Boolean(), nullable=False, server_default="true"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "font_family", sa.String(60), nullable=False, server_default="Inter"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "font_size", sa.SmallInteger(), nullable=False, server_default="40"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "font_color", sa.String(9), nullable=False, server_default="#FFFFFF"
        ),
        schema="ai",
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "caption_position", sa.String(10), nullable=False, server_default="bottom"
        ),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("video_tasks", "caption_position", schema="ai")
    op.drop_column("video_tasks", "font_color", schema="ai")
    op.drop_column("video_tasks", "font_size", schema="ai")
    op.drop_column("video_tasks", "font_family", schema="ai")
    op.drop_column("video_tasks", "add_subtitles", schema="ai")
    op.drop_column("video_tasks", "wide_format", schema="ai")
    op.drop_column("video_tasks", "caption_style", schema="ai")

    op.drop_column("video_clips", "title", schema="ai")
    op.drop_column("video_clips", "thumbnail_public_id", schema="ai")
    op.drop_column("video_clips", "thumbnail_url", schema="ai")

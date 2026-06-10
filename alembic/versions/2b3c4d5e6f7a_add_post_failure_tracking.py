"""add per-post failure tracking

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-09 10:00:00.000000

Lets the UI show which pipeline stage a post failed at, and retry it:
- Adds 'failed' value to ai."ContentStatus" enum.
- Adds failed_stage VARCHAR(50) + error_reason TEXT to ai.content_posts
  (the generation pipeline records the failing node + reason here).
- Adds failed_stage VARCHAR(50) to ai.published_posts (the publish
  pipeline already stored error_message; now it persists the stage too).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "ALTER TYPE ai.\"ContentStatus\" ADD VALUE IF NOT EXISTS 'failed'"
            )
        )

    op.add_column(
        "content_posts",
        sa.Column("failed_stage", sa.String(length=50), nullable=True),
        schema="ai",
    )
    op.add_column(
        "content_posts",
        sa.Column("error_reason", sa.Text(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "published_posts",
        sa.Column("failed_stage", sa.String(length=50), nullable=True),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("published_posts", "failed_stage", schema="ai")
    op.drop_column("content_posts", "error_reason", schema="ai")
    op.drop_column("content_posts", "failed_stage", schema="ai")
    # Postgres has no DROP VALUE for enums; leave 'failed' in place.

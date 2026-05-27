"""add human_feedback + last_revision_targets + regenerating status

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-19 21:00:00.000000

Supports human-feedback-driven post regeneration:
- Adds 'regenerating' value to ai."ContentStatus" enum.
- Adds human_feedback TEXT and last_revision_targets JSONB columns to
  ai.content_posts so we can audit user feedback and the LLM-classified
  regeneration targets used for each revision pass.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    # alembic wraps migrations in one by default, so commit first.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "ALTER TYPE ai.\"ContentStatus\" ADD VALUE IF NOT EXISTS 'regenerating'"
            )
        )

    op.add_column(
        "content_posts",
        sa.Column("human_feedback", sa.Text(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "content_posts",
        sa.Column(
            "last_revision_targets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("content_posts", "last_revision_targets", schema="ai")
    op.drop_column("content_posts", "human_feedback", schema="ai")
    # Postgres has no DROP VALUE for enums; leave 'regenerating' in place.

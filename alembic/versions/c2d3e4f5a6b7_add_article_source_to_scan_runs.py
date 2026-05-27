"""add_article_source_to_scan_runs

Revision ID: c2d3e4f5a6b7
Revises: a0b1c2d3e4f5
Create Date: 2026-04-30 12:00:00.000000

Adds source_type/source_url columns to ai.scan_runs so the express
"Create Post from Article URL" pipeline can mark a scan as
article-driven instead of HackerNews-driven, and remember the URL.

Also adds an 'article' value to the platform enum so synthetic
TrendItem rows produced from a single article have a sensible
platform label distinct from real social platforms.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scan_runs",
        sa.Column("source_type", sa.String(length=32), nullable=True),
        schema="ai",
    )
    op.add_column(
        "scan_runs",
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        schema="ai",
    )
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'article'")


def downgrade() -> None:
    op.drop_column("scan_runs", "source_url", schema="ai")
    op.drop_column("scan_runs", "source_type", schema="ai")
    # Postgres cannot drop enum values; the 'article' value is left in place.

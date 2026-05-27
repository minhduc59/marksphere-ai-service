"""add current_step to scan_runs

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_runs",
        sa.Column("current_step", sa.String(50), nullable=True),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("scan_runs", "current_step", schema="ai")

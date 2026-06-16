"""add triggered_type to scan_runs and pipeline_runs

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-06-12 11:30:00.000000

Lets the Pipeline Control Center label each run as "manual" (user-triggered)
or "scheduled" (recurring daemon). Both paths previously set only
``triggered_by`` (a user UUID), so manual and scheduled runs were
indistinguishable. The new column is set at every creation site; existing
rows stay NULL and render as "—" in the UI.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scan_runs",
        sa.Column("triggered_type", sa.String(length=20), nullable=True),
        schema="ai",
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("triggered_type", sa.String(length=20), nullable=True),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "triggered_type", schema="ai")
    op.drop_column("scan_runs", "triggered_type", schema="ai")

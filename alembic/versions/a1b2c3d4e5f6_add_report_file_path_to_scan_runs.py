"""add_report_file_path_to_scan_runs

Revision ID: a1b2c3d4e5f6
Revises: f254285a977d
Create Date: 2026-03-27 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f254285a977d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scan_runs', sa.Column('report_file_path', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('scan_runs', 'report_file_path')

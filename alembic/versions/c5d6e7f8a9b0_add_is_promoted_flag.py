"""add_is_promoted_flag

Revision ID: c5d6e7f8a9b0
Revises: 421be74de12c
Create Date: 2026-04-03 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = '421be74de12c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'trend_items',
        sa.Column('is_promoted', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'content_posts',
        sa.Column('is_promoted', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('content_posts', 'is_promoted')
    op.drop_column('trend_items', 'is_promoted')

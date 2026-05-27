"""video_tasks: add reframe_mode

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-16 10:00:00.000000

Adds reframe_mode ('static' | 'smart') so users can opt into subject-tracking
reframing (Autocrop-vertical) for 9:16 output. Defaults to 'static' to keep
existing rows on the current fixed-crop behaviour.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_tasks',
        sa.Column('reframe_mode', sa.String(16), nullable=False, server_default='static'),
        schema='ai',
    )


def downgrade() -> None:
    op.drop_column('video_tasks', 'reframe_mode', schema='ai')

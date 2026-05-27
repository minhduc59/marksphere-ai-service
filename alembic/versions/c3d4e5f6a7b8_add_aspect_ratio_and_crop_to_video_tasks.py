"""video_tasks: add aspect_ratio, crop_x, crop_y

Revision ID: c3d4e5f6a7b8
Revises: 905d3dcfdaa8
Create Date: 2026-05-15 16:00:00.000000

Replaces the binary wide_format flag with a named aspect_ratio field
and adds crop_x / crop_y offsets (0.0–1.0) so users can position the
crop window within the source video.  Existing rows get safe defaults:
'9:16' aspect_ratio (same behaviour as wide_format=False) and centred
crop (0.5 / 0.5).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = '905d3dcfdaa8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_tasks',
        sa.Column('aspect_ratio', sa.String(10), nullable=False, server_default='9:16'),
        schema='ai',
    )
    op.add_column(
        'video_tasks',
        sa.Column('crop_x', sa.Float, nullable=False, server_default='0.5'),
        schema='ai',
    )
    op.add_column(
        'video_tasks',
        sa.Column('crop_y', sa.Float, nullable=False, server_default='0.5'),
        schema='ai',
    )


def downgrade() -> None:
    op.drop_column('video_tasks', 'crop_y', schema='ai')
    op.drop_column('video_tasks', 'crop_x', schema='ai')
    op.drop_column('video_tasks', 'aspect_ratio', schema='ai')

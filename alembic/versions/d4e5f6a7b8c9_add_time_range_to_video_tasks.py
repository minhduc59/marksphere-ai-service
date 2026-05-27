"""add start_time_s and end_time_s to video_tasks

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-15 17:00:00.000000

Adds a [start_time_s, end_time_s] window to video_tasks so users can
bracket the portion of a long video the AI should analyze and clip.
end_time_s = 0.0 means "no end limit — process to the end of the video".
The download step will trim the source video to this window before
transcription, reducing download size and processing time.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_tasks',
        sa.Column('start_time_s', sa.Float(), nullable=False, server_default='0.0'),
        schema='ai',
    )
    op.add_column(
        'video_tasks',
        sa.Column('end_time_s', sa.Float(), nullable=False, server_default='0.0'),
        schema='ai',
    )


def downgrade() -> None:
    op.drop_column('video_tasks', 'end_time_s', schema='ai')
    op.drop_column('video_tasks', 'start_time_s', schema='ai')

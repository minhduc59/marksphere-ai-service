"""merge_video_clipper_and_article_source_branches

Revision ID: 905d3dcfdaa8
Revises: b8c9d0e1f2a3, c2d3e4f5a6b7
Create Date: 2026-05-15 15:28:02.149616
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '905d3dcfdaa8'
down_revision: Union[str, None] = ('b8c9d0e1f2a3', 'c2d3e4f5a6b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

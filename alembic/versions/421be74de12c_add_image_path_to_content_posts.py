"""add_image_path_to_content_posts

Revision ID: 421be74de12c
Revises: b9c0d1e2f3a4
Create Date: 2026-04-02 16:09:08.329722
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '421be74de12c'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('content_posts', sa.Column('image_path', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('content_posts', 'image_path')

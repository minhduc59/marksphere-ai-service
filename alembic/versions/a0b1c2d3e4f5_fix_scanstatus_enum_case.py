"""fix scanstatus enum values to lowercase

Revision ID: a0b1c2d3e4f5
Revises: f2a3b4c5d6e7
Create Date: 2026-04-12 08:30:00.000000

The initial migration created the scanstatus enum with uppercase labels
(PENDING, RUNNING, ...) but the Python ScanStatus enum uses lowercase
(pending, running, ...). This migration renames each label to match.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [
    ("PENDING", "pending"),
    ("RUNNING", "running"),
    ("COMPLETED", "completed"),
    ("PARTIAL", "partial"),
    ("FAILED", "failed"),
]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE scanstatus RENAME VALUE '{old}' TO '{new}'")


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE scanstatus RENAME VALUE '{new}' TO '{old}'")

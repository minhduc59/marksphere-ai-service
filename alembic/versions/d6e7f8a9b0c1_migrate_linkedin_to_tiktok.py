"""migrate_linkedin_to_tiktok

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-04-10 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Old LinkedIn formats -> new TikTok formats
FORMAT_MIGRATION = {
    "thought_leadership": "quick_tips",
    "case_study": "trending_breakdown",
    "tutorial": "did_you_know",
    "industry_analysis": "tutorial_hack",
    "career_advice": "myth_busters",
    "behind_the_scenes": "behind_the_tech",
    # "hot_take" stays the same
}


def upgrade() -> None:
    # --- 1. Add new PostFormat enum values ---
    for new_val in ["quick_tips", "trending_breakdown", "did_you_know",
                     "tutorial_hack", "myth_busters", "behind_the_tech"]:
        op.execute(f"ALTER TYPE postformat ADD VALUE IF NOT EXISTS '{new_val}'")

    # Commit so new enum values are visible in the same transaction
    op.execute("COMMIT")

    # --- 2. Update existing rows to use new format values ---
    for old_val, new_val in FORMAT_MIGRATION.items():
        op.execute(
            f"UPDATE content_posts SET format = '{new_val}' WHERE format = '{old_val}'"
        )

    # --- 3. Rename linkedin columns ---
    op.alter_column("trend_items", "linkedin_angles",
                    new_column_name="content_angles")
    op.alter_column("content_posts", "linkedin_angle_used",
                    new_column_name="content_angle_used")


def downgrade() -> None:
    # Rename columns back
    op.alter_column("trend_items", "content_angles",
                    new_column_name="linkedin_angles")
    op.alter_column("content_posts", "content_angle_used",
                    new_column_name="linkedin_angle_used")

    # Revert format values
    reverse = {v: k for k, v in FORMAT_MIGRATION.items()}
    for new_val, old_val in reverse.items():
        op.execute(
            f"UPDATE content_posts SET format = '{old_val}' WHERE format = '{new_val}'"
        )

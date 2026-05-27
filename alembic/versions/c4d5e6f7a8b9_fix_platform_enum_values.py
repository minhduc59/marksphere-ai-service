"""fix_platform_enum_values

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-29 17:00:00.000000

The initial migration created the platform enum with UPPERCASE values
(YOUTUBE, TIKTOK, TWITTER, INSTAGRAM, GOOGLE_TRENDS) but the Python
enum uses lowercase ('youtube', 'google_news'). This migration recreates
the enum with the correct lowercase values and removes stale platforms.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Old DB values -> new Python enum values
_VALUE_MAP = {
    "YOUTUBE": "youtube",
    "TIKTOK": "tiktok",
    "TWITTER": "twitter",
    "INSTAGRAM": "instagram",
    "GOOGLE_TRENDS": "google_trends",
    "google_news": "google_news",
    # If already lowercase, keep as-is
    "youtube": "youtube",
}

_NEW_VALUES = ("youtube", "google_news")


def upgrade() -> None:
    # 1. Drop indexes that reference the platform column
    op.execute("DROP INDEX IF EXISTS ix_trend_items_platform_category")

    # 2. Change column to VARCHAR temporarily
    op.execute("ALTER TABLE trend_items ALTER COLUMN platform TYPE VARCHAR USING platform::text")

    # 3. Update existing rows to lowercase values
    for old_val, new_val in _VALUE_MAP.items():
        if old_val != new_val:
            op.execute(
                f"UPDATE trend_items SET platform = '{new_val}' WHERE platform = '{old_val}'"
            )

    # 4. Delete rows with platforms that no longer exist in the Python enum
    valid = ", ".join(f"'{v}'" for v in _NEW_VALUES)
    op.execute(f"DELETE FROM trend_items WHERE platform NOT IN ({valid})")

    # 5. Drop old enum type and create new one
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute("CREATE TYPE platform AS ENUM ('youtube', 'google_news')")

    # 6. Change column back to the new enum
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN platform TYPE platform "
        "USING platform::platform"
    )

    # 7. Recreate the composite index
    op.execute(
        "CREATE INDEX ix_trend_items_platform_category "
        "ON trend_items (platform, category)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_trend_items_platform_category")
    op.execute("ALTER TABLE trend_items ALTER COLUMN platform TYPE VARCHAR USING platform::text")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute(
        "CREATE TYPE platform AS ENUM "
        "('YOUTUBE', 'TIKTOK', 'TWITTER', 'INSTAGRAM', 'GOOGLE_TRENDS', 'google_news')"
    )
    op.execute(
        "UPDATE trend_items SET platform = 'YOUTUBE' WHERE platform = 'youtube'"
    )
    op.execute(
        "ALTER TABLE trend_items ALTER COLUMN platform TYPE platform "
        "USING platform::platform"
    )
    op.execute(
        "CREATE INDEX ix_trend_items_platform_category "
        "ON trend_items (platform, category)"
    )

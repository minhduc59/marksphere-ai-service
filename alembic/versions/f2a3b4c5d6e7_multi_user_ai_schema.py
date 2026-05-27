"""multi-user: move tables to ai schema + add user_id FKs

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-11 10:00:00.000000

Breaking migration for the NestJS backend API layer introduction.

Changes:
1. Creates 'ai' and 'app' PostgreSQL schemas.
2. Moves every existing table into the 'ai' schema.
3. Adds user_id / triggered_by / created_by / published_by / owner_id columns
   to user-scoped tables. Columns are nullable initially because app.users
   is owned by NestJS and may be empty at migration time; NestJS is
   responsible for backfilling and (later) making them NOT NULL.
4. Drops the single-user unique implicit assumption on user_platform_tokens
   by adding a (user_id, platform) composite unique constraint.

trend_items and engagement_time_slots intentionally stay global (shared
HackerNews data, shared engagement statistics).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES_TO_MOVE = [
    "scan_runs",
    "trend_items",
    "trend_comments",
    "content_posts",
    "published_posts",
    "engagement_time_slots",
    "scan_schedules",
    "user_platform_tokens",
]


def upgrade() -> None:
    # 1. Create schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    # 2. Move all existing tables from public -> ai
    for table in TABLES_TO_MOVE:
        op.execute(f"ALTER TABLE IF EXISTS public.{table} SET SCHEMA ai")

    # 3. Add user-scoping columns (nullable; NestJS will backfill).
    #    No FK to app.users yet — NestJS owns that table and will add the FK
    #    after it has bootstrapped the users table via Prisma migrations.
    op.add_column(
        "scan_runs",
        sa.Column("triggered_by", UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.create_index(
        "ix_ai_scan_runs_triggered_by",
        "scan_runs",
        ["triggered_by"],
        schema="ai",
    )

    op.add_column(
        "content_posts",
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.create_index(
        "ix_ai_content_posts_created_by",
        "content_posts",
        ["created_by"],
        schema="ai",
    )

    op.add_column(
        "published_posts",
        sa.Column("published_by", UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.create_index(
        "ix_ai_published_posts_published_by",
        "published_posts",
        ["published_by"],
        schema="ai",
    )

    op.add_column(
        "scan_schedules",
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.create_index(
        "ix_ai_scan_schedules_owner_id",
        "scan_schedules",
        ["owner_id"],
        schema="ai",
    )

    op.add_column(
        "user_platform_tokens",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.create_unique_constraint(
        "uq_user_platform_tokens_user_platform",
        "user_platform_tokens",
        ["user_id", "platform"],
        schema="ai",
    )


def downgrade() -> None:
    # Drop composite unique and user scoping columns
    op.drop_constraint(
        "uq_user_platform_tokens_user_platform",
        "user_platform_tokens",
        schema="ai",
        type_="unique",
    )
    op.drop_column("user_platform_tokens", "user_id", schema="ai")

    op.drop_index("ix_ai_scan_schedules_owner_id", "scan_schedules", schema="ai")
    op.drop_column("scan_schedules", "owner_id", schema="ai")

    op.drop_index("ix_ai_published_posts_published_by", "published_posts", schema="ai")
    op.drop_column("published_posts", "published_by", schema="ai")

    op.drop_index("ix_ai_content_posts_created_by", "content_posts", schema="ai")
    op.drop_column("content_posts", "created_by", schema="ai")

    op.drop_index("ix_ai_scan_runs_triggered_by", "scan_runs", schema="ai")
    op.drop_column("scan_runs", "triggered_by", schema="ai")

    # Move tables back to public
    for table in TABLES_TO_MOVE:
        op.execute(f"ALTER TABLE IF EXISTS ai.{table} SET SCHEMA public")

    op.execute("DROP SCHEMA IF EXISTS app")
    op.execute("DROP SCHEMA IF EXISTS ai")

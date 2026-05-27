"""move_enums_to_ai_schema

Revision ID: d1e2f3a4b5c6
Revises: f2a3b4c5d6e7
Create Date: 2026-05-01 21:00:00.000000

Prisma multiSchema expects enum types to live in the declared schema
("ai") and to use the exact Prisma enum name (CamelCase). Previously
these types were created in the public schema with lowercase names by
SQLAlchemy/Alembic. This migration moves and renames them so that
Prisma-generated SQL casts (e.g. $1::"ai"."ContentStatus") resolve.

Tables reference types by OID, not by name, so the data is unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text('ALTER TYPE public.contentstatus SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.contentstatus RENAME TO "ContentStatus"'))

    op.execute(sa.text('ALTER TYPE public.scanstatus SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.scanstatus RENAME TO "ScanStatus"'))

    op.execute(sa.text('ALTER TYPE public.platform SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.platform RENAME TO "AiPlatform"'))

    op.execute(sa.text('ALTER TYPE public.sentiment SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.sentiment RENAME TO "Sentiment"'))

    op.execute(sa.text('ALTER TYPE public.trendlifecycle SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.trendlifecycle RENAME TO "TrendLifecycle"'))

    op.execute(sa.text('ALTER TYPE public.engagementprediction SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.engagementprediction RENAME TO "EngagementPrediction"'))

    op.execute(sa.text('ALTER TYPE public.sourcetype SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.sourcetype RENAME TO "SourceType"'))

    op.execute(sa.text('ALTER TYPE public.postformat SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.postformat RENAME TO "PostFormat"'))

    op.execute(sa.text('ALTER TYPE public.publishstatus SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.publishstatus RENAME TO "PublishStatus"'))

    op.execute(sa.text('ALTER TYPE public.publishmode SET SCHEMA ai'))
    op.execute(sa.text('ALTER TYPE ai.publishmode RENAME TO "PublishMode"'))


def downgrade() -> None:
    op.execute(sa.text('ALTER TYPE ai."PublishMode" RENAME TO publishmode'))
    op.execute(sa.text('ALTER TYPE ai.publishmode SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."PublishStatus" RENAME TO publishstatus'))
    op.execute(sa.text('ALTER TYPE ai.publishstatus SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."PostFormat" RENAME TO postformat'))
    op.execute(sa.text('ALTER TYPE ai.postformat SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."SourceType" RENAME TO sourcetype'))
    op.execute(sa.text('ALTER TYPE ai.sourcetype SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."EngagementPrediction" RENAME TO engagementprediction'))
    op.execute(sa.text('ALTER TYPE ai.engagementprediction SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."TrendLifecycle" RENAME TO trendlifecycle'))
    op.execute(sa.text('ALTER TYPE ai.trendlifecycle SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."Sentiment" RENAME TO sentiment'))
    op.execute(sa.text('ALTER TYPE ai.sentiment SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."AiPlatform" RENAME TO platform'))
    op.execute(sa.text('ALTER TYPE ai.platform SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."ScanStatus" RENAME TO scanstatus'))
    op.execute(sa.text('ALTER TYPE ai.scanstatus SET SCHEMA public'))

    op.execute(sa.text('ALTER TYPE ai."ContentStatus" RENAME TO contentstatus'))
    op.execute(sa.text('ALTER TYPE ai.contentstatus SET SCHEMA public'))

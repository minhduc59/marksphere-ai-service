"""add_pipeline_runs

Revision ID: 1a2b3c4d5e6f
Revises: 143e8f1d71e3
Create Date: 2026-06-05 22:00:00.000000

Adds ai.pipeline_runs — the parent orchestration record for the end-to-end
pipeline (Trending Scanner → Post Generation → Publishing Post). It wraps a
single scan execution (scan_run_id) and aggregates the generated/published
post ids so the unified 3-stage status can be served from one resource.
Reuses the existing ai."ScanStatus" enum.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "143e8f1d71e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai.pipeline_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            triggered_by UUID,
            status ai."ScanStatus" NOT NULL DEFAULT 'pending',
            stage VARCHAR(20),
            current_step VARCHAR(50),
            scan_run_id UUID,
            content_post_ids JSON NOT NULL DEFAULT '[]',
            published_post_ids JSON NOT NULL DEFAULT '[]',
            total_items_found INTEGER NOT NULL DEFAULT 0,
            error VARCHAR,
            options JSON,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            duration_ms INTEGER
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_pipeline_runs_triggered_by ON ai.pipeline_runs(triggered_by)"
    )
    op.execute(
        "CREATE INDEX ix_pipeline_runs_scan_run_id ON ai.pipeline_runs(scan_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai.pipeline_runs")

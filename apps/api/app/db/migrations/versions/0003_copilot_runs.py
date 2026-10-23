"""Durable Copilot jobs, confirmations and results (PRD F2.3/§7.2)."""

import sqlalchemy as sa
from alembic import op

revision = "0003_copilot_runs"
down_revision = "0002_score_components"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("confirmation", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_runs_status", "copilot_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_copilot_runs_status", table_name="copilot_runs")
    op.drop_table("copilot_runs")

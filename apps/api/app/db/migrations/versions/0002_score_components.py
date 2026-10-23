"""Persist raw signals for reproducible pool normalization (PRD §9).

Revision ID: 0002_score_components
Revises: 0001_initial_schema
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_score_components"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing aggregate scores cannot be decomposed honestly. Leave them null
    # until intake is explicitly rerun rather than fabricate a backfill.
    op.add_column("profiles", sa.Column("score_components", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "score_components")

"""initial schema — all 9 tables from app/db/models.py

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-23

NOTE: Hand-written against app/db/models.py since `alembic revision
--autogenerate` couldn't run yet (pyproject.toml/uv env was being built in
parallel by another agent) — verify with `cd apps/api && uv run alembic
check` once the environment is installed. Columns, types, nullability,
primary keys, and foreign keys below are transcribed directly from
app/db/models.py (Job, Application, Profile, ResumeChunk, JdRequirement,
SkillTaxonomy, VectorJob, Review, Event). Do not autogenerate over this
file without diffing first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all 9 tables, in FK-safe order."""

    # jobs — no FKs.
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("raw_jd", sa.Text(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # applications — FK -> jobs.id
    op.create_table(
        "applications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("resume_path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("vector_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # profiles — application_id is both PK and FK -> applications.id
    op.create_table(
        "profiles",
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("requirement_matches", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("application_id"),
    )

    # resume_chunks — FK -> applications.id. No vector column: Pinecone is derived.
    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("chunk_idx", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("pinecone_id", sa.String(), nullable=False),
        sa.Column("embed_model", sa.String(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # jd_requirements — FK -> jobs.id
    op.create_table(
        "jd_requirements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),  # must_have | nice_to_have
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("pinecone_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # skill_taxonomy — no FKs.
    op.create_table(
        "skill_taxonomy",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("canonical", sa.String(), nullable=False),
        sa.Column("alt_labels", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),  # onet | esco
        sa.Column("pinecone_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # vector_jobs — no FKs. Outbox/work log for dual-write (PRD §8.5).
    op.create_table(
        "vector_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),  # upsert | reindex | delete
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # reviews — FK -> applications.id
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("reviewer_role", sa.String(), nullable=False),  # hr | tech_lead
        sa.Column("rubric", sa.JSON(), nullable=False),
        sa.Column("overall", sa.Float(), nullable=False),
        sa.Column("comments", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # events — FK -> applications.id. Audit log (AGENTS.md invariant 4).
    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop all tables in reverse FK-safe order."""
    op.drop_table("events")
    op.drop_table("reviews")
    op.drop_table("vector_jobs")
    op.drop_table("skill_taxonomy")
    op.drop_table("jd_requirements")
    op.drop_table("resume_chunks")
    op.drop_table("profiles")
    op.drop_table("applications")
    op.drop_table("jobs")

"""Read-only Postgres-derived vector parity checks (PRD §8.5–8.7)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, JdRequirement, Job, ResumeChunk, SkillTaxonomy
from app.rag import namespaces
from app.rag.indexer import audit_namespace


async def audit_vectors(db: Session, namespace: str | None = None) -> list[dict[str, Any]]:
    """Compare known namespace contents with IDs derived from Postgres.

    Candidate summaries currently exist only in the dense index. Applications
    without persisted resume chunks have no expected summary: empty or not-yet
    processed applications must not manufacture missing-vector errors.

    An explicit namespace must exactly match a known namespace in the current
    configured environment. This check never creates indexes, embeds text,
    modifies records, or commits the caller's transaction.
    """
    env = get_settings().pinecone_env
    with db.no_autoflush:
        job_ids = list(db.scalars(select(Job.id).order_by(Job.id)).all())
        expected: dict[str, tuple[list[str], list[str] | None]] = {
            namespaces.taxonomy_namespace(env): (
                sorted(set(db.scalars(select(SkillTaxonomy.pinecone_id)).all())),
                None,
            )
        }
        for job_id in job_ids:
            requirement_ids = list(
                db.scalars(
                    select(JdRequirement.pinecone_id).where(JdRequirement.job_id == job_id)
                ).all()
            )
            chunk_ids = list(
                db.scalars(
                    select(ResumeChunk.pinecone_id)
                    .join(Application, ResumeChunk.application_id == Application.id)
                    .where(Application.job_id == job_id)
                ).all()
            )
            summary_application_ids = list(
                db.scalars(
                    select(Application.id)
                    .join(ResumeChunk, ResumeChunk.application_id == Application.id)
                    .where(Application.job_id == job_id)
                    .distinct()
                    .order_by(Application.id)
                ).all()
            )
            expected[namespaces.jd_namespace(env, job_id)] = (sorted(set(requirement_ids)), None)
            expected[namespaces.resumes_namespace(env, job_id)] = (sorted(set(chunk_ids)), None)
            expected[namespaces.candidates_namespace(env, job_id)] = (
                [
                    namespaces.candidate_summary_record_id(value)
                    for value in summary_application_ids
                ],
                [],
            )

    if namespace is not None and namespace not in expected:
        raise ValueError(f"Unknown namespace for the configured environment: {namespace!r}")
    selected = [namespace] if namespace is not None else list(expected)
    reports: list[dict[str, Any]] = []
    for selected_namespace in selected:
        dense_ids, sparse_ids = expected[selected_namespace]
        reports.append(
            await audit_namespace(selected_namespace, dense_ids, expected_sparse_ids=sparse_ids)
        )
    return reports

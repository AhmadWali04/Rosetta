"""Candidate-summary similarity through the vector abstraction and PG hydration."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Application, ResumeChunk
from app.db.session import session_scope
from app.rag.embeddings import get_embedder
from app.rag.namespaces import candidate_summary_record_id, candidates_namespace
from app.rag.vector_store import get_vector_store


def find_similar_candidates(
    job_id: str, candidate_id: str, k: int | None = None
) -> tuple[list[str], list[str]]:
    settings = get_settings()
    limit = max(1, min(k or settings.copilot_pool_limit, settings.copilot_pool_limit))
    with session_scope() as db:
        application = db.get(Application, candidate_id)
        if application is None or application.job_id != job_id:
            raise ValueError("Candidate is outside the requested job")
        chunks = list(
            db.scalars(
                select(ResumeChunk)
                .where(ResumeChunk.application_id == candidate_id)
                .order_by(ResumeChunk.chunk_idx)
            ).all()
        )
        preferred = [
            chunk.text for chunk in chunks if chunk.section.lower() in {"skills", "experience"}
        ]
        summary = "\n\n".join(preferred or [chunk.text for chunk in chunks])
        others = list(
            db.scalars(
                select(Application)
                .where(Application.job_id == job_id, Application.id != candidate_id)
                .order_by(Application.id)
            ).all()
        )
        allowed = {candidate_summary_record_id(row.id): row.id for row in others}
    namespace = candidates_namespace(settings.pinecone_env, job_id)
    store = get_vector_store("dense")

    async def search() -> list[str]:
        if not summary.strip():
            return []
        [vector] = await get_embedder().embed_dense([summary])
        matches = await store.query(namespace, vector, limit + 1)
        return list(dict.fromkeys(allowed[match.id] for match in matches if match.id in allowed))[
            :limit
        ]

    try:
        ids = asyncio.run(search())
        if ids:
            return ids, []
    except Exception:
        pass
    return [], ["Similarity search unavailable or empty; no similarity claim was made."]

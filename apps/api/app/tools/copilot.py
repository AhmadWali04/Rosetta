"""Scoped copilot tools; citation text always comes from Postgres."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Application, JdRequirement, ResumeChunk, SkillTaxonomy
from app.db.session import session_scope
from app.graphs.state import CopilotCitation, CopilotProposal
from app.rag.namespaces import resumes_namespace, taxonomy_namespace
from app.rag.retriever import hybrid_search
from app.routes.hr_schemas import StatusChange
from app.services import hr


def get_candidate_profile(job_id: str, candidate_id: str) -> dict[str, Any]:
    with session_scope() as db:
        application = db.get(Application, candidate_id)
        if application is None or application.job_id != job_id:
            raise ValueError("Candidate is outside the requested job")
        result = hr.detail(db, candidate_id).model_dump(mode="json")
        result["links"] = application.links
        return result


def get_jd_requirements(job_id: str) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = db.scalars(select(JdRequirement).where(JdRequirement.job_id == job_id)
                          .order_by(JdRequirement.id)).all()
        return [{"id": row.id, "text": row.text, "kind": row.kind, "weight": row.weight}
                for row in rows]


def rank_pool(job_id: str, status: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as db:
        return [row.model_dump(mode="json") for row in hr.pipeline(
            db, job_id=job_id, status=status)[:get_settings().copilot_pool_limit]]


def _citation(chunk: ResumeChunk) -> CopilotCitation:
    return CopilotCitation(chunk_id=chunk.id, application_id=chunk.application_id,
                           text=chunk.text, section=chunk.section,
                           char_start=chunk.char_start, char_end=chunk.char_end)


def search_resume_chunks(job_id: str, candidate_id: str, query: str
                         ) -> tuple[list[CopilotCitation], list[str]]:
    settings = get_settings()
    warnings: list[str] = []
    with session_scope() as db:
        application = db.get(Application, candidate_id)
        if application is None or application.job_id != job_id:
            raise ValueError("Candidate is outside the requested job")
        chunks = list(db.scalars(select(ResumeChunk).where(
            ResumeChunk.application_id == candidate_id).order_by(ResumeChunk.chunk_idx)).all())
        selected: list[ResumeChunk] = []
        if application.vector_status == "indexed":
            try:
                matches = asyncio.run(hybrid_search(
                    resumes_namespace(settings.pinecone_env, job_id), query,
                    filter={"application_id": {"$eq": candidate_id}},
                    final_k=settings.copilot_max_evidence_chunks))
                by_id = {chunk.pinecone_id: chunk for chunk in chunks}
                selected = [by_id[match.id] for match in matches if match.id in by_id]
            except Exception:
                warnings.append("Vector search unavailable; using Postgres resume evidence.")
        if not selected:
            warnings.append("Postgres fallback: vector evidence was unavailable or empty.")
            tokens = set(query.lower().split())
            selected = sorted(chunks, key=lambda chunk: (
                -sum(token in chunk.text.lower() for token in tokens), chunk.chunk_idx))
        return [_citation(chunk) for chunk in selected[:settings.copilot_max_evidence_chunks]], warnings


def validate_citations(job_id: str, scope: str, chunk_ids: list[str]) -> list[CopilotCitation]:
    if not chunk_ids:
        return []
    with session_scope() as db:
        statement = select(ResumeChunk).join(Application).where(
            Application.job_id == job_id, ResumeChunk.id.in_(chunk_ids))
        if scope.startswith("candidate:"):
            statement = statement.where(ResumeChunk.application_id == scope.split(":", 1)[1])
        elif scope != "pool":
            raise ValueError("Invalid copilot scope")
        by_id = {row.id: row for row in db.scalars(statement).all()}
        return [_citation(by_id[chunk_id]) for chunk_id in dict.fromkeys(chunk_ids)
                if chunk_id in by_id]


def search_taxonomy(term: str) -> list[dict[str, str]]:
    settings = get_settings()
    with session_scope() as db:
        matches = []
        try:
            matches = asyncio.run(hybrid_search(taxonomy_namespace(settings.pinecone_env), term,
                                               final_k=settings.retriever_final_k))
        except Exception:
            pass
        match_ids = {match.id for match in matches}
        rows = db.scalars(select(SkillTaxonomy).order_by(SkillTaxonomy.id)).all()
        selected = [row for row in rows if row.pinecone_id in match_ids]
        if not selected:
            selected = [row for row in rows if term.casefold() in row.canonical.casefold()
                        or any(term.casefold() in label.casefold() for label in row.alt_labels)]
        return [{"canonical": row.canonical, "description": row.description}
                for row in selected[:settings.retriever_final_k]]


def find_similar(job_id: str, candidate_id: str, k: int | None = None
                 ) -> tuple[list[str], list[str]]:
    from app.rag.similarity import find_similar_candidates

    get_candidate_profile(job_id, candidate_id)
    return find_similar_candidates(job_id, candidate_id, k)


def update_status(job_id: str, proposal: CopilotProposal, confirmed: bool) -> None:
    if confirmed is not True:
        raise ValueError("Explicit human confirmation required")
    with session_scope() as db:
        application = db.get(Application, proposal.application_id)
        if application is None or application.job_id != job_id:
            raise ValueError("Candidate is outside the requested job")
        hr.label(db, proposal.application_id,
                 StatusChange(status=proposal.status, reason=proposal.reason))  # type: ignore[arg-type]

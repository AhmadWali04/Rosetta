"""Hybrid retrieval: dense + sparse queries merged by reciprocal rank fusion,
with an optional (currently no-op) rerank step (PRD §8.4).

`hybrid_search()` is the one function graphs/tools should call for
requirement-matching-style retrieval. It is the ONLY thing in this module
that talks to `app.rag.vector_store` / `app.rag.embeddings` — callers never
construct a `VectorStore` or an embedder themselves for this path.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings
from app.rag.embeddings import get_embedder
from app.rag.vector_store import ScoredMatch, get_vector_store


class RetrievedMatch(BaseModel):
    """One hybrid-search result: a record id, its fused RRF (or reranked)
    score, and Pinecone's metadata copy for that record.

    CRITICAL (AGENTS.md invariant #1 and #7; PRD §8.3): `metadata` is
    Pinecone's convenience copy, used here only for filtering/debugging
    display. It is NEVER ground truth for citations. Pinecone's metadata
    `text` field (and any `char_start`/`char_end` it carries) must NEVER be
    shown to a user or fed to an LLM as evidence — Postgres `resume_chunks`
    is the only source of truth for citation text and spans. Callers of
    `hybrid_search()` MUST hydrate the real chunk text from Postgres by
    `id` (the chunk's `pinecone_id`) before using it for anything
    citation-shaped. Getting this backwards is exactly the mistake AGENTS.md
    invariant #7 exists to prevent.
    """

    id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


def _rrf_merge(result_lists: list[list[ScoredMatch]], rrf_k: int) -> list[RetrievedMatch]:
    """Reciprocal rank fusion across one or more ranked result lists.

    `rrf_score(id) = sum over lists containing id of 1 / (rrf_k + rank)`,
    where `rank` is the 0-based position of that id WITHIN each list (the
    top hit of a list contributes `1 / (rrf_k + 0)`, not its raw score) —
    this is deliberately rank-based, not score-based, since dense cosine
    scores and sparse dotproduct scores aren't on comparable scales.

    Dedupes by id. Metadata is taken from whichever list's entry is seen
    first for that id (both lists describe the same underlying Pinecone
    record under the same id scheme, so it should not matter which one
    "wins").
    """
    rrf_scores: dict[str, float] = {}
    metadata_by_id: dict[str, dict[str, Any]] = {}

    for results in result_lists:
        for rank, match in enumerate(results):
            rrf_scores[match.id] = rrf_scores.get(match.id, 0.0) + 1.0 / (rrf_k + rank)
            metadata_by_id.setdefault(match.id, match.metadata)

    merged = [
        RetrievedMatch(id=record_id, score=score, metadata=metadata_by_id[record_id])
        for record_id, score in rrf_scores.items()
    ]
    merged.sort(key=lambda m: m.score, reverse=True)
    return merged


def _rerank_noop(candidates: list[RetrievedMatch]) -> list[RetrievedMatch]:
    """Rerank step, currently a CLEARLY-LABELED NO-OP PASS-THROUGH.

    Why a no-op rather than a real call to Pinecone's hosted
    `bge-reranker-v2-m3`: PRD §11 explicitly scopes rerank tuning/ablation
    to M5's eval harness ("Behind a flag; its value is measured in eval"),
    and PRD §19 says the decision to keep or drop rerank is deferred to
    that ablation ("leave it to testing... if it costs too much or is too
    slow we will get rid of it"). Building a real reranker call here, in
    M1, ahead of that measurement would be scope creep into M5's job. This
    function exists so `hybrid_search()`'s `settings.rerank_enabled` branch
    has somewhere real to call — when M5's ablation lands, swap this
    implementation for a verified `rerank-documents`-shaped Pinecone
    Inference call (check the installed SDK's current call shape first,
    the same way `_pinecone_shared.py`'s sparse-query shape was verified)
    without needing to touch `hybrid_search()` itself.
    """
    return candidates


async def hybrid_search(
    namespace: str,
    query_text: str,
    top_k: int | None = None,
    filter: dict[str, Any] | None = None,
    final_k: int | None = None,
) -> list[RetrievedMatch]:
    """Hybrid (dense + sparse) retrieval, merged by reciprocal rank fusion
    (PRD §8.4).

    NEVER treat the returned `RetrievedMatch.metadata` as citation-ready
    text — see `RetrievedMatch`'s docstring. Callers must hydrate the real
    chunk text/spans from Postgres `resume_chunks` by `id`.

    Args:
        namespace: Pinecone namespace to query (dense and sparse indexes
            use identical namespace names, per PRD §8.2).
        query_text: Natural-language query to embed and search with.
        top_k: How many candidates to retrieve from EACH of the dense and
            sparse indexes before fusion. Defaults to
            `settings.retriever_top_k`.
        filter: Optional metadata filter applied identically to both the
            dense and sparse queries, e.g. `{"application_id": {"$eq": "a_123"}}`.
        final_k: How many fused results to return. Defaults to
            `settings.retriever_final_k`.

    Algorithm (PRD §8.4):
        1. Embed `query_text` once dense and once sparse.
        2. Query the dense and sparse `VectorStore`s in parallel, same
           namespace and filter, `top_k` each.
        3. Merge and dedupe by record id with reciprocal rank fusion.
        4. Optionally rerank (currently a no-op pass-through — see
           `_rerank_noop`).
        5. Return the top `final_k`.
    """
    settings = get_settings()
    effective_top_k = top_k if top_k is not None else settings.retriever_top_k
    effective_final_k = final_k if final_k is not None else settings.retriever_final_k

    embedder = get_embedder()
    dense_vectors, sparse_vectors = await asyncio.gather(
        embedder.embed_dense([query_text]),
        embedder.embed_sparse([query_text]),
    )
    dense_vector = dense_vectors[0]
    sparse_vector = sparse_vectors[0]

    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")
    dense_results, sparse_results = await asyncio.gather(
        dense_store.query(namespace, dense_vector, effective_top_k, filter),
        sparse_store.query_sparse(
            namespace, sparse_vector.indices, sparse_vector.values, effective_top_k, filter
        ),
    )

    merged = _rrf_merge([dense_results, sparse_results], rrf_k=settings.rrf_k)

    if settings.rerank_enabled:
        merged = _rerank_noop(merged)

    return merged[:effective_final_k]

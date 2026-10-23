"""Index lifecycle + parity audit (PRD §17 M0, §8.7 "vector-audit").

Scope, deliberately narrow — read this before adding a `reindex_namespace`:

`ensure_indexes()` creates the two serverless Pinecone indexes if they don't
exist yet (delegates the actual SDK calls to
`app/rag/vector_store/admin.py`, so this module itself never imports the
Pinecone SDK — see that module's docstring for why).

This module does NOT implement a generic `reindex_namespace(namespace)`
that rebuilds a namespace from Postgres. "Rebuild this namespace" requires
job-specific knowledge of how to re-derive each namespace's records from
Postgres rows (taxonomy rows -> taxonomy records, JD requirements -> JD
records, resume chunks -> chunk records, candidate summaries -> summary
records) — knowledge that belongs with whatever code already builds those
records: the seed script (Agent D, M0) for `taxonomy`/`jd-*`, and the
intake graph (M1) for `resumes-*`/`candidates-*`. Bolting that per-namespace
knowledge onto this module would mean reaching into another agent's/
milestone's not-yet-written code, which the task scoping explicitly called
out as out of bounds for this file.

Instead, `audit_namespace()` gives any future caller (a `make vector-audit`
command, the seed script, M1's eventual reindex job) a namespace-agnostic
comparison primitive: hand it the IDs Postgres thinks should exist for a
namespace, and it reports what Pinecone is missing or holds that it
shouldn't (orphans), split out per dense/sparse index since the two can
drift independently.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.rag.vector_store import get_vector_store
from app.rag.vector_store.admin import ensure_serverless_indexes


async def ensure_indexes() -> dict[str, Any]:
    """Idempotently create `skillbridge-dense` and `skillbridge-sparse`
    (PRD §8.2) if they don't already exist. No-op for
    `VECTOR_BACKEND=memory` — returns `{"skipped": "memory backend"}`.

    Returns `{index_name: "created" | "already_existed"}` otherwise.
    """
    settings = get_settings()
    if settings.vector_backend == "memory":
        return {"skipped": "memory backend"}
    return await ensure_serverless_indexes()


async def audit_namespace(namespace: str, expected_ids: list[str]) -> dict[str, Any]:
    """Compare `expected_ids` (supplied by the caller from Postgres — this
    module has no Postgres access of its own) against what the dense and
    sparse `VectorStore`s actually hold for `namespace`.

    Returns:
        {
          "namespace": namespace,
          "missing": [...],     # expected but absent from EITHER index
          "orphaned": [...],    # present in EITHER index but not expected
          "missing_dense": [...],
          "missing_sparse": [...],
          "parity": bool,       # True iff missing == [] and orphaned == []
        }
    """
    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")
    dense_ids, sparse_ids = await asyncio.gather(
        dense_store.list_ids(namespace),
        sparse_store.list_ids(namespace),
    )

    expected = set(expected_ids)
    dense_set = set(dense_ids)
    sparse_set = set(sparse_ids)
    actual_either = dense_set | sparse_set

    missing = sorted(expected - actual_either)
    orphaned = sorted(actual_either - expected)
    missing_dense = sorted(expected - dense_set)
    missing_sparse = sorted(expected - sparse_set)

    return {
        "namespace": namespace,
        "missing": missing,
        "orphaned": orphaned,
        "missing_dense": missing_dense,
        "missing_sparse": missing_sparse,
        "parity": not missing and not orphaned,
    }

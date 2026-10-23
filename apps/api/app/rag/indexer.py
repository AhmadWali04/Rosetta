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

`wait_for_freshness()` (M1, PRD §8.6) is the freshness-poll primitive the
Chunk & Index node uses right after upserting: Pinecone serverless is
eventually consistent, so a just-upserted record may not be immediately
queryable. This function only reports success/failure honestly — deciding
what to do on a `False` (fall back to in-state chunk data, flag the run)
is the Chunk & Index node's job, not this module's (PRD §8.6).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import get_settings
from app.rag.vector_store import VectorStore, get_vector_store
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


async def wait_for_freshness(
    namespace: str,
    expected_record_count: int | None = None,
    last_upserted_id: str | None = None,
    timeout_s: float | None = None,
    *,
    poll_interval_s: float = 0.5,
) -> bool:
    """Poll the dense and sparse `VectorStore`s until newly-upserted records
    are visible, or `timeout_s` elapses (PRD §8.6).

    No-op, returns `True` immediately for `VECTOR_BACKEND=memory` — the
    in-memory backend is synchronous (upsert completes before this is ever
    called), so nothing is ever "not fresh" there (PRD §8.8).

    Precision order when both are given, or when only one is given:
    - `last_upserted_id` (preferred when present): poll via
      `fetch(namespace, [last_upserted_id])` on BOTH stores — more precise
      than a count, since a namespace can hold pre-existing records, which
      would make a bare count check pass or fail for the wrong reason.
    - `expected_record_count` (fallback, used when `last_upserted_id` is
      not given): poll via `record_count(namespace) >= expected_record_count`
      on BOTH stores.
    At least one of the two must be given, or there is nothing to poll for.

    Returns `True` once fresh, `False` on timeout. This function only
    reports success/failure honestly — it is the CALLER's job (the Chunk &
    Index node, PRD §8.6) to decide what to do with `False` (fall back to
    in-state chunk data and flag the run; not this function's concern).

    `poll_interval_s` (default 0.5s, per PRD §8.6's "polls... every) is a
    keyword-only seam for tests that want to exercise the polling loop
    without waiting on the real default cadence/timeout; production
    callers should leave it at the default.
    """
    if last_upserted_id is None and expected_record_count is None:
        raise ValueError(
            "wait_for_freshness requires at least one of expected_record_count or last_upserted_id"
        )

    settings = get_settings()
    if settings.vector_backend == "memory":
        return True

    effective_timeout = timeout_s if timeout_s is not None else settings.vector_freshness_timeout_s
    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")

    deadline = time.monotonic() + effective_timeout
    while True:
        if await _namespace_is_fresh(
            dense_store, sparse_store, namespace, expected_record_count, last_upserted_id
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(poll_interval_s)


async def _namespace_is_fresh(
    dense_store: VectorStore,
    sparse_store: VectorStore,
    namespace: str,
    expected_record_count: int | None,
    last_upserted_id: str | None,
) -> bool:
    """One freshness check, per the precision order documented on
    `wait_for_freshness`: prefer fetching `last_upserted_id` when given,
    else fall back to a record-count comparison."""
    if last_upserted_id is not None:
        dense_hit, sparse_hit = await asyncio.gather(
            dense_store.fetch(namespace, [last_upserted_id]),
            sparse_store.fetch(namespace, [last_upserted_id]),
        )
        return bool(dense_hit) and bool(sparse_hit)

    assert expected_record_count is not None  # guaranteed by the caller's upfront check
    dense_count, sparse_count = await asyncio.gather(
        dense_store.record_count(namespace),
        sparse_store.record_count(namespace),
    )
    return dense_count >= expected_record_count and sparse_count >= expected_record_count

"""In-memory `VectorStore` backend. No network, pure Python — used for unit
tests (`VECTOR_BACKEND=memory`, AGENTS.md "Testing rules") and quick local
dev. Nothing here is persisted; process restart loses all data.

Design notes / judgment calls:

- Storage is a plain `dict[namespace, dict[record_id, VectorRecord]]`. All
  methods are `async def` to satisfy the `VectorStore` ABC, but none of them
  actually await anything — that's expected for a pure in-memory backend.
- `query()` assumes the records in a given namespace are HOMOGENEOUS: either
  every record there is dense (`values` populated) or every record is sparse
  (`sparse_indices`/`sparse_values` populated). Mixing the two within one
  namespace is not supported — in practice this already matches how the
  real Pinecone backends are used: one `VectorStore` instance is bound to a
  single (dense or sparse) index, and each index's namespaces only ever
  hold that index's vector shape.
  - Dense case: score = cosine similarity between the query `vector` and
    each candidate's `values`.
  - Sparse case: `query()` now raises `NotImplementedError` pointing at
    `query_sparse` (see below) instead of silently misusing the dense
    signature. Previously (M0) this method tried to repurpose the dense
    `vector: list[float]` argument as a positionally-aligned stand-in for a
    sparse query, which only worked by accident and never emulated
    Pinecone's real sparse scoring. `query_sparse` is the real, correctly
    shaped replacement — use it for any sparse-bound namespace.
- `query_sparse()` is the real sparse-query path (PRD §8.4): it takes the
  query's sparse vector as parallel `indices`/`values` arrays (matching
  `VectorRecord.sparse_indices`/`sparse_values` and
  `app.rag.embeddings.SparseVector`) and scores each candidate by the
  standard sparse dot product — `sum(value_i * value_j)` over indices
  present in BOTH the query and the candidate record. This is a faithful,
  if simple, emulation of Pinecone's sparse `dotproduct` metric (PRD §8.2),
  unlike the old `query()` hack.
- `filter` supports only single/multi-field `{"field": {"$eq": value}}`
  metadata filters, applied before ranking. Any other operator raises
  `NotImplementedError` with a clear message, per the task spec — we'd
  rather fail loudly than silently return wrong results.
- `fetch()`'s `score` field is meaningless/unused for this backend (and for
  Pinecone's real fetch API too) — only `id` + `metadata` matter. We return
  `1.0` as a harmless constant.
"""

from __future__ import annotations

import math
from typing import Any

from app.rag.vector_store.base import ScoredMatch, VectorRecord, VectorStore


def _is_eq_filter(filter: dict[str, Any]) -> None:
    """Validate that every field in `filter` uses only the `$eq` operator.
    Raises NotImplementedError for anything else."""
    for field_name, condition in filter.items():
        if not isinstance(condition, dict):
            raise NotImplementedError(
                f"MemoryVectorStore filter: field {field_name!r} must map to an "
                f"operator dict like {{'$eq': value}}, got {condition!r}"
            )
        operators = set(condition.keys())
        if operators != {"$eq"}:
            raise NotImplementedError(
                f"MemoryVectorStore only supports the '$eq' filter operator; "
                f"field {field_name!r} used {sorted(operators)!r}"
            )


def _matches_filter(metadata: dict[str, Any], filter: dict[str, Any] | None) -> bool:
    if not filter:
        return True
    _is_eq_filter(filter)
    for field_name, condition in filter.items():
        if metadata.get(field_name) != condition["$eq"]:
            return False
    return True


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _sparse_dot_product(
    query_indices: list[int],
    query_values: list[float],
    record: VectorRecord,
) -> float:
    """Real sparse dot product: `sum(value_i * value_j)` over vocabulary
    indices present in BOTH the query and the record (PRD §8.2's
    `dotproduct` metric). Indices absent from either side contribute 0."""
    query_weights = dict(zip(query_indices, query_values, strict=False))
    record_indices = record.sparse_indices or []
    record_values = record.sparse_values or []
    score = 0.0
    for idx, val in zip(record_indices, record_values, strict=False):
        query_weight = query_weights.get(idx)
        if query_weight is not None:
            score += query_weight * val
    return score


class MemoryVectorStore(VectorStore):
    """Pure in-memory `VectorStore`. See module docstring for scoring rules
    and the sparse-query simplification."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, VectorRecord]] = {}

    def _namespace(self, namespace: str) -> dict[str, VectorRecord]:
        return self._data.setdefault(namespace, {})

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        ns = self._namespace(namespace)
        for record in records:
            ns[record.id] = record

    async def query(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        ns = self._namespace(namespace)
        candidates = [r for r in ns.values() if _matches_filter(r.metadata, filter)]
        if not candidates:
            return []

        is_sparse = any(c.sparse_indices for c in candidates)
        if is_sparse:
            raise NotImplementedError(
                "MemoryVectorStore.query() is dense-only; this namespace holds "
                "sparse-shaped records. Use query_sparse() instead (see module "
                "docstring)."
            )
        scored = [(c, _cosine_similarity(vector, c.values)) for c in candidates]

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            ScoredMatch(id=c.id, score=score, metadata=c.metadata) for c, score in scored[:top_k]
        ]

    async def query_sparse(
        self,
        namespace: str,
        indices: list[int],
        values: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        ns = self._namespace(namespace)
        candidates = [r for r in ns.values() if _matches_filter(r.metadata, filter)]
        if not candidates:
            return []

        scored = [(c, _sparse_dot_product(indices, values, c)) for c in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            ScoredMatch(id=c.id, score=score, metadata=c.metadata) for c, score in scored[:top_k]
        ]

    async def fetch(self, namespace: str, ids: list[str]) -> list[ScoredMatch]:
        ns = self._namespace(namespace)
        results = []
        for record_id in ids:
            record = ns.get(record_id)
            if record is not None:
                # score is meaningless/unused for fetch; only id + metadata matter.
                results.append(ScoredMatch(id=record.id, score=1.0, metadata=record.metadata))
        return results

    async def delete_by_prefix(self, namespace: str, prefix: str) -> int:
        ns = self._namespace(namespace)
        to_delete = [record_id for record_id in ns if record_id.startswith(prefix)]
        for record_id in to_delete:
            del ns[record_id]
        return len(to_delete)

    async def list_ids(self, namespace: str) -> list[str]:
        return list(self._namespace(namespace).keys())

    async def record_count(self, namespace: str) -> int:
        return len(self._namespace(namespace))

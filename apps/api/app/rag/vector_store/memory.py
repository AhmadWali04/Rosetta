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
  namespace is not supported and will produce meaningless scores — in
  practice this already matches how the real Pinecone backends are used:
  one `VectorStore` instance is bound to a single (dense or sparse) index,
  and each index's namespaces only ever hold that index's vector shape.
  - Dense case: score = cosine similarity between the query `vector` and
    each candidate's `values`.
  - Sparse case: the abstract interface's `query(vector: list[float], ...)`
    signature has no clean way to pass a sparse query (indices + weights).
    Simplifying choice (documented here rather than getting stuck on it):
    treat the incoming `vector` as a DENSE array aligned to the union of
    sparse indices seen so far in the namespace (i.e. position `i` of
    `vector` corresponds to the i-th distinct index encountered, in
    first-seen order), and score by dot product over the candidate's
    populated (index, value) pairs against that same positional mapping.
    This is good enough for unit tests and local dev; it is NOT a faithful
    emulation of Pinecone's native sparse scoring and should not be trusted
    for anything beyond that. Real sparse-vector testing should go through
    `pinecone_local.py` against the Docker emulator.
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


def _sparse_score(
    query_vector: list[float],
    record: VectorRecord,
    index_order: dict[int, int],
) -> float:
    """Dot product of the record's sparse (index, value) pairs against the
    query vector, using `index_order` to map a sparse vocabulary index to a
    position in the dense-shaped `query_vector`. See module docstring."""
    indices = record.sparse_indices or []
    values = record.sparse_values or []
    score = 0.0
    for idx, val in zip(indices, values, strict=False):
        pos = index_order.get(idx)
        if pos is not None and pos < len(query_vector):
            score += query_vector[pos] * val
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
            # Build the "union of indices seen so far, first-seen order" map.
            index_order: dict[int, int] = {}
            for c in candidates:
                for idx in c.sparse_indices or []:
                    if idx not in index_order:
                        index_order[idx] = len(index_order)
            scored = [(c, _sparse_score(vector, c, index_order)) for c in candidates]
        else:
            scored = [(c, _cosine_similarity(vector, c.values)) for c in candidates]

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

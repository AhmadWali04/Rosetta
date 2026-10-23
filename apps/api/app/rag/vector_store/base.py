"""VectorStore interface (PRD §8.8). Graph code, tools, and routes only ever
see this interface — never a provider SDK directly (AGENTS.md invariant 8).

Implementations: memory.py (unit tests, no network), pinecone_local.py
(Docker emulator, integration tests + offline demo), pinecone_cloud.py
(real demo + eval).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    """One record to upsert. `values` is the dense OR sparse vector depending
    on which index this is written to; callers pick the index, not the record.

    `values` holds a DENSE vector (one float per embedding dimension) —
    populate this for records written to a dense index. `sparse_indices` /
    `sparse_values` together hold a SPARSE vector (parallel arrays of
    vocabulary-index -> weight; sparse vectors are far too high-dimensional
    to represent as a dense `list[float]`) — populate this pair for records
    written to a sparse index. A record should populate exactly one of the
    two representations (dense `values`, or the sparse pair), never both;
    for a sparse record, pass `values=[]`. This is a caller/implementation
    invariant for M0 — the class itself does not enforce it.
    """

    id: str
    values: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


@dataclass(frozen=True)
class ScoredMatch:
    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """One instance is bound to a single Pinecone index (dense or sparse)."""

    @abstractmethod
    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        """Upsert in batches of <= settings.pinecone_upsert_batch_size,
        with retry/backoff (AGENTS.md "Pinecone rules")."""

    @abstractmethod
    async def query(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        """The DENSE-only query path: `vector` is one dense embedding (one
        float per embedding dimension). Query with an optional metadata
        filter, e.g. {"application_id": {"$eq": "a_123"}}.

        This signature has no clean way to carry a SPARSE query (parallel
        index/value arrays over a huge vocabulary) — use `query_sparse`
        instead for that. A store bound to a sparse-shaped index/namespace
        may raise `NotImplementedError` here pointing at `query_sparse`
        rather than trying to misuse this signature (see each
        implementation's docstring for whether it does).
        """

    @abstractmethod
    async def query_sparse(
        self,
        namespace: str,
        indices: list[int],
        values: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        """The real SPARSE-query path (PRD §8.4, `app/rag/retriever.py`).

        `indices`/`values` are the query's sparse vector as parallel arrays
        (vocabulary index -> weight), matching the shape of
        `VectorRecord.sparse_indices`/`sparse_values` and
        `app.rag.embeddings.SparseVector`. This is the counterpart to
        `query()` for stores bound to a sparse index; `query()` stays
        dense-only (see its docstring) rather than trying to overload one
        method signature for both vector shapes.
        """

    @abstractmethod
    async def fetch(self, namespace: str, ids: list[str]) -> list[ScoredMatch]:
        """Fetch specific records by ID (used for freshness polling, PRD §8.6)."""

    @abstractmethod
    async def delete_by_prefix(self, namespace: str, prefix: str) -> int:
        """Delete every record whose ID starts with `prefix`. Returns count deleted.
        Used by the application delete path (PRD §8.7)."""

    @abstractmethod
    async def list_ids(self, namespace: str) -> list[str]:
        """List every record ID in a namespace. Used by `make vector-audit` to
        compare Postgres <-> Pinecone parity."""

    @abstractmethod
    async def record_count(self, namespace: str) -> int:
        """Namespace record count, used by the freshness poll (PRD §8.6)."""

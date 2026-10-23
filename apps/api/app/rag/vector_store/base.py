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
    """

    id: str
    values: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


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
        """Query with an optional metadata filter, e.g. {"application_id": {"$eq": "a_123"}}."""

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

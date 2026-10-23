"""Shared `VectorStore` implementation over a real `pinecone` SDK `Index`
handle, used by both `pinecone_local.py` (Docker emulator) and
`pinecone_cloud.py` (real Pinecone). The two differ only in how they build
the `pinecone.Pinecone` client and resolve an `Index` handle (local: by
`host`, no auth; cloud: by API key, resolved via the control plane) — every
other behaviour (batching/retry on upsert, dense-vs-sparse payload shaping,
query, query_sparse, fetch, delete-by-prefix, list, record_count) is identical, so it
lives here once instead of being duplicated and risking drift between the
two files.

This module is private (leading underscore, not re-exported from
`app/rag/vector_store/__init__.py`). Like `pinecone_local.py` and
`pinecone_cloud.py`, it lives inside `app/rag/vector_store/` — the only
package (along with `app/rag/embeddings.py`) allowed to import the Pinecone
SDK (AGENTS.md invariant 8).

The SDK's primary client is sync/blocking, so every call into it is wrapped
in `asyncio.to_thread(...)` rather than reaching for an async-native
Pinecone client variant — simpler and more robust within the M0 timebox
(per the task spec), at the cost of one thread-hop per call.

CORRECTNESS FIX (found and patched while verifying this module, not
reverting anyone's design — see the `_get_index()` docstring below for
details): obtaining a `pinecone.Index` handle is itself a blocking network
call in this SDK — confirmed by reproduction: `Pinecone(api_key=...).Index(
name=...)` synchronously does `self.indexes.describe(name)` ->
`self._http.get(...)` to resolve the index's host before returning. An
earlier version of this module built that handle eagerly in each
subclass's `__init__`, which is sync and runs outside `asyncio.to_thread`
— so constructing a store from an async call site (e.g. `get_vector_store()`
inside a FastAPI route or graph node) would block the event loop for that
HTTP round-trip. `_get_index()` instead resolves and caches the handle
lazily, the first time any async method needs it, via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import Any

from app.config import get_settings
from app.rag.vector_store.base import ScoredMatch, VectorRecord, VectorStore


class PineconeSDKVectorStore(VectorStore):
    """Common logic for the two real-SDK backends. Not meant to be
    instantiated directly: subclasses must set `self._vector_type` ("dense"
    or "sparse") in their own `__init__`, and override `_build_index()`
    (blocking: construct/resolve the `pinecone.Index` handle) instead of
    setting `self._index` directly — see `_get_index()`.

    `self._vector_type` is derived by each subclass by comparing the
    `index_name` it was constructed with against
    `settings.pinecone_dense_index` / `settings.pinecone_sparse_index`,
    because `factory.py`'s constructor calls (per the task spec) only pass
    `index_name` + `host`/`api_key` — not an explicit dense/sparse flag.
    """

    _vector_type: str

    def __init__(self) -> None:
        self._index: Any | None = None

    @abstractmethod
    def _build_index(self) -> Any:
        """Blocking: construct (and resolve the host for, if needed) this
        instance's `pinecone.Index` handle. Called at most once per store
        instance, inside `asyncio.to_thread` (see `_get_index`)."""

    async def _get_index(self) -> Any:
        """Lazily resolve and cache the `pinecone.Index` handle on first
        use, off the event loop. See the module docstring's "CORRECTNESS
        FIX" note for why this is lazy rather than built in `__init__`."""
        if self._index is None:
            self._index = await asyncio.to_thread(self._build_index)
        return self._index

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> None:
        settings = get_settings()
        index = await self._get_index()
        batch_size = settings.pinecone_upsert_batch_size
        max_retries = settings.pinecone_upsert_max_retries

        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            payload = [self._to_upsert_payload(r) for r in batch]
            await self._upsert_batch_with_retry(index, namespace, payload, max_retries)

    async def _upsert_batch_with_retry(
        self,
        index: Any,
        namespace: str,
        payload: list[dict[str, Any]],
        max_retries: int,
    ) -> None:
        """Retry one batch with exponential backoff (`AGENTS.md` "Pinecone
        rules"). Raises the last error once retries are exhausted."""
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                await asyncio.to_thread(index.upsert, vectors=payload, namespace=namespace)
                return
            except Exception as exc:  # noqa: BLE001 - deliberately broad: retry any SDK error
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
        assert last_exc is not None  # max_retries >= 1 is assumed
        raise last_exc

    @staticmethod
    def _to_upsert_payload(record: VectorRecord) -> dict[str, Any]:
        """Build the Pinecone SDK's expected upsert dict for one record.

        Dense:  {"id", "values", "metadata"}
        Sparse: {"id", "sparse_values": {"indices": [...], "values": [...]}, "metadata"}

        The sparse shape is confirmed against Pinecone's "bring your own
        sparse vectors" upsert example: `sparse_values` is a nested dict
        with `indices` and `values` keys, not two flat top-level fields.
        """
        if record.sparse_indices is not None or record.sparse_values is not None:
            return {
                "id": record.id,
                "sparse_values": {
                    "indices": record.sparse_indices or [],
                    "values": record.sparse_values or [],
                },
                "metadata": record.metadata,
            }
        return {"id": record.id, "values": record.values, "metadata": record.metadata}

    async def query(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        if self._vector_type == "sparse":
            # `query()` stays dense-only (see base.py's docstring): the
            # abstract `vector: list[float]` signature has no clean way to
            # carry a sparse query. M1 lands the real sparse path as
            # `query_sparse()` below — use that for a sparse-index-bound
            # store instead of calling this method.
            raise NotImplementedError(
                "Sparse-index query() has no faithful representation through "
                "VectorStore.query(vector: list[float]) - this store is bound "
                "to a sparse index. Use query_sparse() instead (see base.py)."
            )

        index = await self._get_index()
        response = await asyncio.to_thread(
            index.query,
            namespace=namespace,
            vector=vector,
            top_k=top_k,
            filter=filter,
            include_metadata=True,
        )
        return [
            ScoredMatch(id=match.id, score=match.score, metadata=dict(match.metadata or {}))
            for match in response.matches
        ]

    async def query_sparse(
        self,
        namespace: str,
        indices: list[int],
        values: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredMatch]:
        """Real sparse query via the Pinecone SDK's `sparse_vector=` kwarg.

        Call shape VERIFIED against the installed SDK (`pinecone==10.1.0`,
        `inspect.signature(pinecone.Index.query)` and
        `inspect.getsource(pinecone.index.__init__.query)`): `Index.query()`
        accepts `sparse_vector: SparseValues | Mapping[str, Any] | None`,
        and the method's own docstring example passes a plain dict —
        `sparse_vector={"indices": [17, 42, 108], "values": [0.4, 0.9, 0.2]}`
        — so a plain `{"indices": [...], "values": [...]}` mapping (no
        `SparseValues` import needed) is confirmed to work, matching the
        same nested shape `_to_upsert_payload()` already uses for
        `sparse_values` on upsert. `vector=` is simply omitted for a
        sparse-only index query, per the same docstring
        ("omit for sparse-only indexes (use *sparse_vector* instead)").
        """
        if self._vector_type == "dense":
            raise NotImplementedError(
                "query_sparse() was called on a dense-index-bound store; use "
                "query() instead for dense vectors."
            )

        index = await self._get_index()
        response = await asyncio.to_thread(
            index.query,
            namespace=namespace,
            sparse_vector={"indices": indices, "values": values},
            top_k=top_k,
            filter=filter,
            include_metadata=True,
        )
        return [
            ScoredMatch(id=match.id, score=match.score, metadata=dict(match.metadata or {}))
            for match in response.matches
        ]

    async def fetch(self, namespace: str, ids: list[str]) -> list[ScoredMatch]:
        index = await self._get_index()
        response = await asyncio.to_thread(index.fetch, ids=ids, namespace=namespace)
        vectors = response.vectors or {}
        # `score` is meaningless/unused for fetch (same as MemoryVectorStore's
        # fetch) - only `id` + `metadata` matter here. 1.0 is a harmless
        # constant, not a real similarity score.
        return [
            ScoredMatch(id=vec_id, score=1.0, metadata=dict(vec.metadata or {}))
            for vec_id, vec in vectors.items()
        ]

    async def delete_by_prefix(self, namespace: str, prefix: str) -> int:
        """Pinecone has no native prefix-delete: list every ID in the
        namespace, filter client-side, then delete that explicit ID list."""
        index = await self._get_index()
        all_ids = await self.list_ids(namespace)
        matching = [record_id for record_id in all_ids if record_id.startswith(prefix)]
        if not matching:
            return 0
        await asyncio.to_thread(index.delete, ids=matching, namespace=namespace)
        return len(matching)

    async def list_ids(self, namespace: str) -> list[str]:
        """`index.list(namespace=...)` is a generator yielding one
        `ListResponse` per page (confirmed against the installed SDK,
        `pinecone==10.1.0`: `Index.list()` returns `Iterator[ListResponse]`,
        each carrying `.vectors: list[ListItem]`, each `ListItem` exposing
        just `.id`) - collect every page's IDs."""
        index = await self._get_index()

        def _collect() -> list[str]:
            collected: list[str] = []
            for page in index.list(namespace=namespace):
                collected.extend(item.id for item in page.vectors if item.id is not None)
            return collected

        return await asyncio.to_thread(_collect)

    async def record_count(self, namespace: str) -> int:
        index = await self._get_index()
        stats = await asyncio.to_thread(index.describe_index_stats)
        namespaces = getattr(stats, "namespaces", None) or {}
        ns_stats = namespaces.get(namespace)
        if ns_stats is None:
            return 0
        if isinstance(ns_stats, dict):
            return int(ns_stats.get("vector_count", 0))
        return int(getattr(ns_stats, "vector_count", 0))

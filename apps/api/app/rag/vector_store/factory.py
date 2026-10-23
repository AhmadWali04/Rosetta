"""Builds the right `VectorStore` for the configured backend (PRD §8.8).

Graph code, tools, and routes call `get_vector_store(kind)` and never
construct a backend class directly — that keeps `VECTOR_BACKEND` switching
invisible to callers (AGENTS.md invariant 8).
"""

from __future__ import annotations

from typing import Literal

from app.config import get_settings
from app.rag.vector_store.base import VectorStore
from app.rag.vector_store.memory import MemoryVectorStore
from app.rag.vector_store.pinecone_cloud import PineconeCloudVectorStore
from app.rag.vector_store.pinecone_local import PineconeLocalVectorStore

VectorKind = Literal["dense", "sparse"]

# Module-level cache keyed by (backend, kind). Instances are cheap and
# stateless wrappers (aside from the in-memory backend's dict, which we WANT
# to persist across calls within a process so repeated `get_vector_store`
# calls see the same data) so caching is a simple dict rather than
# `functools.lru_cache` (which would need hashable args — fine here, but a
# plain dict is just as clear and easier to clear in tests if ever needed).
_INSTANCES: dict[tuple[str, str], VectorStore] = {}


def get_vector_store(kind: VectorKind) -> VectorStore:
    """Return the `VectorStore` for `kind` ("dense" or "sparse"), selecting
    the implementation based on `settings.vector_backend`.

    Instances are cached per (backend, kind) for the lifetime of the
    process. This matters most for `memory`, where callers need to see the
    same underlying dict across calls (e.g. an upsert in one node and a
    query in the next must hit the same `MemoryVectorStore`).
    """
    settings = get_settings()
    cache_key = (settings.vector_backend, kind)
    if cache_key in _INSTANCES:
        return _INSTANCES[cache_key]

    store: VectorStore
    if settings.vector_backend == "memory":
        store = MemoryVectorStore()
    elif settings.vector_backend == "pinecone-local":
        index_name = (
            settings.pinecone_dense_index if kind == "dense" else settings.pinecone_sparse_index
        )
        store = PineconeLocalVectorStore(
            index_name=index_name,
            host=settings.pinecone_local_host,
        )
    elif settings.vector_backend == "pinecone":
        index_name = (
            settings.pinecone_dense_index if kind == "dense" else settings.pinecone_sparse_index
        )
        store = PineconeCloudVectorStore(
            index_name=index_name,
            api_key=settings.pinecone_api_key,
        )
    else:  # pragma: no cover - Literal in config.py prevents this at type-check time
        raise ValueError(f"Unknown VECTOR_BACKEND: {settings.vector_backend!r}")

    _INSTANCES[cache_key] = store
    return store

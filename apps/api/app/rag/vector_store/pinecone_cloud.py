"""`VectorStore` backend for real Pinecone cloud (PRD §13, §8 - the real
demo and `make eval`).
"""

from __future__ import annotations

from typing import Any

from pinecone import Pinecone

from app.config import get_settings
from app.rag.vector_store._pinecone_shared import PineconeSDKVectorStore


class PineconeCloudVectorStore(PineconeSDKVectorStore):
    """Wraps one real Pinecone serverless index (dense or sparse)."""

    def __init__(self, index_name: str, api_key: str | None) -> None:
        super().__init__()
        settings = get_settings()
        self._vector_type = "sparse" if index_name == settings.pinecone_sparse_index else "dense"
        self._index_name = index_name
        self._api_key = api_key

    def _build_index(self) -> Any:
        """Blocking: resolve the `Index` handle by name. Called lazily via
        `_get_index()` (see `_pinecone_shared.py`'s "CORRECTNESS FIX" note)
        rather than eagerly in `__init__` — confirmed by reproduction that
        `Pinecone(...).Index(name=...)` itself makes a blocking HTTP call
        (`describe(name)`) to resolve the index's host before returning,
        so building it eagerly in a sync `__init__` would block the event
        loop if a store is ever constructed from async code.

        Target-by-name is Pinecone's documented convenience path ("this
        method is convenient for testing but is not recommended for
        production" - docs.pinecone.io/guides/manage-data/target-an-index).
        Fine for M0's scope (seed ingestion); targeting by host is the
        documented production recommendation and worth revisiting once
        this backend is on the hot path for real traffic.
        """
        client = Pinecone(api_key=self._api_key)
        return client.Index(self._index_name)

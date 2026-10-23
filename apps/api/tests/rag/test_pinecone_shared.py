"""Unit tests for `PineconeSDKVectorStore`'s request-building logic
(`_pinecone_shared.py`), without any live network call (AGENTS.md "Testing
rules": unit tests never call a live LLM or the network).

A minimal concrete subclass overrides `_build_index()` to return a fake
`Index`-shaped object whose `query` method just records the kwargs it was
called with — this lets us assert the exact call shape sent to the
Pinecone SDK (sparse_vector dict shape, filter/top_k/namespace plumbing)
without touching any real Pinecone service.

Run with: `cd apps/api && uv run pytest tests/rag/test_pinecone_shared.py -v`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.rag.vector_store._pinecone_shared import PineconeSDKVectorStore

NAMESPACE = "dev-test"


@dataclass
class _FakeMatch:
    id: str
    score: float
    metadata: dict[str, Any] | None = None


@dataclass
class _FakeQueryResponse:
    matches: list[_FakeMatch] = field(default_factory=list)


class _FakeIndex:
    """Records every `query()` call's kwargs for assertion, and returns a
    canned response."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = _FakeQueryResponse(
            matches=[_FakeMatch(id="a", score=0.5, metadata={"section": "experience"})]
        )

    def query(self, **kwargs: Any) -> _FakeQueryResponse:
        self.calls.append(kwargs)
        return self.response


class _FakeVectorStore(PineconeSDKVectorStore):
    """Concrete `PineconeSDKVectorStore` wired to a `_FakeIndex` instead of
    a real Pinecone SDK handle."""

    def __init__(self, vector_type: str) -> None:
        super().__init__()
        self._vector_type = vector_type
        self.fake_index = _FakeIndex()

    def _build_index(self) -> Any:
        return self.fake_index


@pytest.mark.asyncio
async def test_query_sparse_sends_the_verified_sparse_vector_shape() -> None:
    store = _FakeVectorStore(vector_type="sparse")

    results = await store.query_sparse(
        NAMESPACE,
        indices=[17, 42, 108],
        values=[0.4, 0.9, 0.2],
        top_k=5,
        filter={"application_id": {"$eq": "a_123"}},
    )

    assert len(store.fake_index.calls) == 1
    call = store.fake_index.calls[0]
    # Verified call shape (see query_sparse's docstring): a plain dict with
    # "indices"/"values" keys passed to `sparse_vector=`, no `vector=`.
    assert call["sparse_vector"] == {"indices": [17, 42, 108], "values": [0.4, 0.9, 0.2]}
    assert "vector" not in call
    assert call["namespace"] == NAMESPACE
    assert call["top_k"] == 5
    assert call["filter"] == {"application_id": {"$eq": "a_123"}}
    assert call["include_metadata"] is True

    assert len(results) == 1
    assert results[0].id == "a"
    assert results[0].score == 0.5
    assert results[0].metadata == {"section": "experience"}


@pytest.mark.asyncio
async def test_query_sparse_rejects_dense_bound_store() -> None:
    store = _FakeVectorStore(vector_type="dense")

    with pytest.raises(NotImplementedError):
        await store.query_sparse(NAMESPACE, indices=[1], values=[1.0], top_k=5)

    assert store.fake_index.calls == []


@pytest.mark.asyncio
async def test_query_rejects_sparse_bound_store() -> None:
    """query() stays dense-only — sparse-bound stores must use
    query_sparse() instead (see base.py's docstring)."""
    store = _FakeVectorStore(vector_type="sparse")

    with pytest.raises(NotImplementedError):
        await store.query(NAMESPACE, vector=[1.0, 0.0], top_k=5)

    assert store.fake_index.calls == []


@pytest.mark.asyncio
async def test_query_sends_dense_vector_shape() -> None:
    store = _FakeVectorStore(vector_type="dense")

    await store.query(NAMESPACE, vector=[0.1, 0.2, 0.3], top_k=10, filter=None)

    assert len(store.fake_index.calls) == 1
    call = store.fake_index.calls[0]
    assert call["vector"] == [0.1, 0.2, 0.3]
    assert "sparse_vector" not in call
    assert call["namespace"] == NAMESPACE
    assert call["top_k"] == 10
    assert call["include_metadata"] is True

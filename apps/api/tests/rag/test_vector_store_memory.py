"""Unit tests for `MemoryVectorStore` (AGENTS.md "Testing rules": unit tests
never call a live LLM or the network — this backend is pure Python).

Run with: `cd apps/api && uv run pytest tests/rag/test_vector_store_memory.py -v`
"""

from __future__ import annotations

import pytest

from app.rag.vector_store.base import VectorRecord
from app.rag.vector_store.memory import MemoryVectorStore

NAMESPACE = "dev-test"


@pytest.mark.asyncio
async def test_upsert_and_query_roundtrip_ranks_closest_vector_first() -> None:
    store = MemoryVectorStore()
    records = [
        VectorRecord(id="a", values=[1.0, 0.0, 0.0]),
        VectorRecord(id="b", values=[0.0, 1.0, 0.0]),
        VectorRecord(id="c", values=[0.0, 0.0, 1.0]),
    ]
    await store.upsert(NAMESPACE, records)

    # Query vector is near-identical to record "b"'s direction.
    results = await store.query(NAMESPACE, vector=[0.01, 0.99, 0.01], top_k=3)

    assert len(results) == 3
    assert results[0].id == "b"
    # Scores should be sorted descending.
    assert results[0].score >= results[1].score >= results[2].score


@pytest.mark.asyncio
async def test_query_applies_eq_metadata_filter() -> None:
    store = MemoryVectorStore()
    records = [
        VectorRecord(id="a", values=[1.0, 0.0], metadata={"application_id": "app_1"}),
        VectorRecord(id="b", values=[1.0, 0.0], metadata={"application_id": "app_2"}),
        VectorRecord(id="c", values=[1.0, 0.0], metadata={"application_id": "app_2"}),
    ]
    await store.upsert(NAMESPACE, records)

    results = await store.query(
        NAMESPACE,
        vector=[1.0, 0.0],
        top_k=10,
        filter={"application_id": {"$eq": "app_2"}},
    )

    assert {r.id for r in results} == {"b", "c"}


@pytest.mark.asyncio
async def test_query_rejects_unsupported_filter_operator() -> None:
    store = MemoryVectorStore()
    await store.upsert(NAMESPACE, [VectorRecord(id="a", values=[1.0, 0.0])])

    with pytest.raises(NotImplementedError):
        await store.query(
            NAMESPACE,
            vector=[1.0, 0.0],
            top_k=1,
            filter={"score": {"$gt": 0.5}},
        )


@pytest.mark.asyncio
async def test_delete_by_prefix_only_removes_matching_ids() -> None:
    store = MemoryVectorStore()
    records = [
        VectorRecord(id="app_1#chunk#0", values=[1.0, 0.0]),
        VectorRecord(id="app_1#chunk#1", values=[0.0, 1.0]),
        VectorRecord(id="app_1#summary", values=[1.0, 1.0]),
        VectorRecord(id="app_2#chunk#0", values=[0.5, 0.5]),
    ]
    await store.upsert(NAMESPACE, records)

    deleted = await store.delete_by_prefix(NAMESPACE, "app_1#")

    assert deleted == 3
    remaining_ids = set(await store.list_ids(NAMESPACE))
    assert remaining_ids == {"app_2#chunk#0"}
    assert await store.record_count(NAMESPACE) == 1


@pytest.mark.asyncio
async def test_fetch_returns_only_found_ids_with_metadata() -> None:
    store = MemoryVectorStore()
    await store.upsert(
        NAMESPACE,
        [VectorRecord(id="a", values=[1.0], metadata={"text": "hello"})],
    )

    results = await store.fetch(NAMESPACE, ["a", "missing"])

    assert len(results) == 1
    assert results[0].id == "a"
    assert results[0].metadata == {"text": "hello"}


@pytest.mark.asyncio
async def test_namespaces_are_isolated() -> None:
    store = MemoryVectorStore()
    await store.upsert("dev-ns-1", [VectorRecord(id="a", values=[1.0])])
    await store.upsert("dev-ns-2", [VectorRecord(id="b", values=[1.0])])

    assert await store.list_ids("dev-ns-1") == ["a"]
    assert await store.list_ids("dev-ns-2") == ["b"]

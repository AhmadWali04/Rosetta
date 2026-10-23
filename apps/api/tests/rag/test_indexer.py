"""Unit tests for `app.rag.indexer.wait_for_freshness` (PRD §8.6). Pure
Python / monkeypatched fakes, no network and no real sleeping through a
full timeout.

Run with: `cd apps/api && uv run pytest tests/rag/test_indexer.py -v`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import app.rag.indexer as indexer_module
from app.rag.vector_store import ScoredMatch


@dataclass
class _FakeSettings:
    vector_backend: str = "pinecone-local"
    vector_freshness_timeout_s: float = 5.0


class _FakeStore:
    """Minimal `VectorStore`-shaped fake: only `fetch`/`record_count` are
    exercised by `wait_for_freshness`."""

    def __init__(
        self,
        fetch_hits_after: int = 0,
        count_sequence: list[int] | None = None,
    ) -> None:
        # `fetch_hits_after`: number of `fetch()` calls that return empty
        # before a call returns a hit (simulates a slow-to-appear record).
        self._fetch_hits_after = fetch_hits_after
        self._fetch_calls = 0
        self._count_sequence = count_sequence or []
        self._count_calls = 0

    async def fetch(self, namespace: str, ids: list[str]) -> list[ScoredMatch]:
        self._fetch_calls += 1
        if self._fetch_calls > self._fetch_hits_after:
            return [ScoredMatch(id=ids[0], score=1.0, metadata={})]
        return []

    async def record_count(self, namespace: str) -> int:
        idx = min(self._count_calls, len(self._count_sequence) - 1)
        self._count_calls += 1
        return self._count_sequence[idx] if self._count_sequence else 0


@pytest.mark.asyncio
async def test_memory_backend_returns_true_immediately_without_polling(monkeypatch: Any) -> None:
    # Default Settings().vector_backend == "memory" — no monkeypatching needed.
    result = await indexer_module.wait_for_freshness(
        "dev-test", expected_record_count=5, timeout_s=0.01
    )
    assert result is True


@pytest.mark.asyncio
async def test_raises_when_neither_count_nor_id_given() -> None:
    with pytest.raises(ValueError):
        await indexer_module.wait_for_freshness("dev-test")


@pytest.mark.asyncio
async def test_last_upserted_id_becomes_fresh_after_a_few_polls(monkeypatch: Any) -> None:
    dense_store = _FakeStore(fetch_hits_after=2)
    sparse_store = _FakeStore(fetch_hits_after=1)

    def fake_get_vector_store(kind: str) -> _FakeStore:
        return dense_store if kind == "dense" else sparse_store

    monkeypatch.setattr(indexer_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(indexer_module, "get_vector_store", fake_get_vector_store)

    result = await indexer_module.wait_for_freshness(
        "dev-test",
        last_upserted_id="a_123#chunk#0",
        timeout_s=2.0,
        poll_interval_s=0.01,
    )

    assert result is True
    # Became fresh once BOTH stores report a hit on the same poll — dense
    # needed 3 calls (hits_after=2), sparse needed 2 (hits_after=1), so it
    # should have taken at least 3 polls total.
    assert dense_store._fetch_calls >= 3


@pytest.mark.asyncio
async def test_expected_record_count_fallback_used_when_no_id_given(monkeypatch: Any) -> None:
    dense_store = _FakeStore(count_sequence=[0, 1, 3])
    sparse_store = _FakeStore(count_sequence=[0, 2, 3])

    def fake_get_vector_store(kind: str) -> _FakeStore:
        return dense_store if kind == "dense" else sparse_store

    monkeypatch.setattr(indexer_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(indexer_module, "get_vector_store", fake_get_vector_store)

    result = await indexer_module.wait_for_freshness(
        "dev-test",
        expected_record_count=3,
        timeout_s=2.0,
        poll_interval_s=0.01,
    )

    assert result is True


@pytest.mark.asyncio
async def test_times_out_and_returns_false_when_never_fresh(monkeypatch: Any) -> None:
    dense_store = _FakeStore(fetch_hits_after=10_000)  # never hits
    sparse_store = _FakeStore(fetch_hits_after=10_000)

    def fake_get_vector_store(kind: str) -> _FakeStore:
        return dense_store if kind == "dense" else sparse_store

    monkeypatch.setattr(indexer_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(indexer_module, "get_vector_store", fake_get_vector_store)

    result = await indexer_module.wait_for_freshness(
        "dev-test",
        last_upserted_id="a_123#chunk#0",
        timeout_s=0.05,
        poll_interval_s=0.01,
    )

    assert result is False

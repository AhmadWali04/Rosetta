"""Dense + sparse embedding, via Pinecone Inference in real backends or a
deterministic fake in tests/local dev (AGENTS.md repo layout; PRD §8.2 "why
vectors are embedded in app code, not with Pinecone's integrated
embedding" - so this module, and this module alone outside
`app/rag/vector_store/`, is allowed to import the Pinecone SDK, per
AGENTS.md invariant 8).

Callers (the seed script, later the intake graph) should go through
`get_embedder()` and never branch on `settings.vector_backend` themselves -
the real and fake embedders expose the same async `embed_dense`/
`embed_sparse` shape.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings


@dataclass(frozen=True)
class SparseVector:
    """One sparse embedding: parallel arrays of vocabulary index -> weight,
    matching the shape `VectorRecord.sparse_indices`/`sparse_values`
    expect (see `app/rag/vector_store/base.py`)."""

    indices: list[int]
    values: list[float]


class Embedder(Protocol):
    """Uniform shape both the real Pinecone-backed embedder and
    `FakeEmbedder` conform to, so callers never branch on backend."""

    async def embed_dense(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_sparse(self, texts: list[str]) -> list[SparseVector]: ...


# --------------------------------------------------------------------------
# Real backend: Pinecone Inference
# --------------------------------------------------------------------------


def _extract_dense_values(item: Any) -> list[float]:
    """Pinecone's `inference.embed()` response items support dict-style
    subscripting in the SDK's own docs examples (`item['values']`); fall
    back to attribute access in case a given SDK version returns a typed
    object instead."""
    try:
        return list(item["values"])
    except (KeyError, TypeError, IndexError):
        return list(item.values)


def _extract_sparse_values(item: Any) -> SparseVector:
    try:
        return SparseVector(
            indices=list(item["sparse_indices"]), values=list(item["sparse_values"])
        )
    except (KeyError, TypeError, IndexError):
        return SparseVector(indices=list(item.sparse_indices), values=list(item.sparse_values))


async def embed_dense(texts: list[str]) -> list[list[float]]:
    """Dense embeddings via Pinecone Inference (`settings.embedding_model`,
    default `llama-text-embed-v2`). Only meaningful when
    `settings.vector_backend == "pinecone"` (real cloud) - see
    `get_embedder()` for why `pinecone-local` does NOT route here."""
    import asyncio

    import pinecone

    settings = get_settings()
    client = pinecone.Pinecone(api_key=settings.pinecone_api_key)
    response = await asyncio.to_thread(
        client.inference.embed,
        model=settings.embedding_model,
        inputs=texts,
        parameters={"input_type": "passage", "truncate": "END"},
    )
    return [_extract_dense_values(item) for item in response]


async def embed_sparse(texts: list[str]) -> list[SparseVector]:
    """Sparse embeddings via Pinecone Inference (`settings.sparse_model`,
    default `pinecone-sparse-english-v0`)."""
    import asyncio

    import pinecone

    settings = get_settings()
    client = pinecone.Pinecone(api_key=settings.pinecone_api_key)
    response = await asyncio.to_thread(
        client.inference.embed,
        model=settings.sparse_model,
        inputs=texts,
        parameters={"input_type": "passage", "truncate": "END"},
    )
    return [_extract_sparse_values(item) for item in response]


class _PineconeInferenceEmbedder:
    """Thin `Embedder`-shaped wrapper around the module-level
    `embed_dense`/`embed_sparse` functions, so `get_embedder()` can return
    either this or `FakeEmbedder()` uniformly."""

    async def embed_dense(self, texts: list[str]) -> list[list[float]]:
        return await embed_dense(texts)

    async def embed_sparse(self, texts: list[str]) -> list[SparseVector]:
        return await embed_sparse(texts)


# --------------------------------------------------------------------------
# Fake backend: deterministic, hash-based, no network
# --------------------------------------------------------------------------

_FAKE_SPARSE_VOCAB_SIZE = 1000


def _fake_dense_vector(text: str) -> list[float]:
    """Deterministic pseudo-embedding: seed a local RNG from an md5 digest
    of the text so the same text always produces the same vector (no
    network, no shared global RNG state), then L2-normalize so cosine
    similarity behaves sensibly in `MemoryVectorStore`."""
    settings = get_settings()
    seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(settings.embedding_dimension)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _fake_sparse_vector(text: str) -> SparseVector:
    """Deterministic pseudo-sparse-embedding: hash each token into a small
    fixed vocab (`_FAKE_SPARSE_VOCAB_SIZE`), accumulate term counts per
    hashed index, then normalize counts into weights summing to 1. Good
    enough for unit tests/local dev; not a faithful BM25-style sparse model."""
    tokens = [t for t in re.split(r"\W+", text.lower()) if t]
    if not tokens:
        return SparseVector(indices=[], values=[])

    counts: dict[int, float] = {}
    for token in tokens:
        idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % _FAKE_SPARSE_VOCAB_SIZE
        counts[idx] = counts.get(idx, 0.0) + 1.0

    total = sum(counts.values())
    indices = sorted(counts)
    values = [counts[i] / total for i in indices]
    return SparseVector(indices=indices, values=values)


class FakeEmbedder:
    """Deterministic, hash-based embedder with no network calls. Used
    whenever a live embedding model shouldn't be called - unit tests
    (AGENTS.md "Testing rules": "unit tests never call a live LLM or the
    network") and, per this module's `get_embedder()` judgment call, the
    `pinecone-local` backend too (see `get_embedder()` docstring)."""

    async def embed_dense(self, texts: list[str]) -> list[list[float]]:
        return [_fake_dense_vector(t) for t in texts]

    async def embed_sparse(self, texts: list[str]) -> list[SparseVector]:
        return [_fake_sparse_vector(t) for t in texts]


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def get_embedder() -> Embedder:
    """Returns the `Embedder` for the configured backend, so callers (the
    seed script, later the intake graph) never branch on backend
    themselves.

    Judgment call, documented here rather than silently assumed: this maps
    `vector_backend == "pinecone"` to the real Pinecone-Inference-backed
    embedder, and BOTH `"memory"` and `"pinecone-local"` to `FakeEmbedder`.
    The task spec's literal wording ties the fake embedder only to
    `"memory"`, but PRD §8.8 and AGENTS.md "Testing rules" are explicit that
    Pinecone Local "doesn't host the inference models" and that integration
    tests against it "use cached embeddings from
    tests/fixtures/embeddings/" rather than live inference calls. Loading a
    *specific* cached fixture is a test-harness concern that belongs with
    the tests that need one, not with this general-purpose app module; the
    pragmatic middle ground taken here is to default `pinecone-local` to
    the same deterministic `FakeEmbedder` as `memory`; a test that
    specifically wants a realistic cached embedding should load its fixture
    directly instead of going through `get_embedder()`.

    Not cached (unlike `get_vector_store()`): both embedder types are
    stateless, so there's no correctness reason to memoize, and skipping a
    cache avoids a stale-instance footgun across tests that flip
    `settings.vector_backend` via monkeypatching `get_settings()`.
    """
    settings = get_settings()
    if settings.vector_backend == "pinecone":
        return _PineconeInferenceEmbedder()
    return FakeEmbedder()

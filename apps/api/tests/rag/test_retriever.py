"""Unit tests for `app.rag.retriever.hybrid_search` (PRD §8.4). Runs with
`VECTOR_BACKEND=memory` (the test default, see `app.config.Settings`) and
`FakeEmbedder` (`get_embedder()`'s default for any non-"pinecone" backend)
— no network.

Each test uses its own namespace: `get_vector_store()` caches
`MemoryVectorStore` instances for the lifetime of the test process, so
reusing a namespace across tests would leak records between them.

Run with: `cd apps/api && uv run pytest tests/rag/test_retriever.py -v`
"""

from __future__ import annotations

import pytest

from app.rag.embeddings import get_embedder
from app.rag.retriever import hybrid_search
from app.rag.vector_store import VectorRecord, get_vector_store


@pytest.mark.asyncio
async def test_hybrid_search_ranks_dual_list_match_above_single_list_matches() -> None:
    namespace = "dev-test-retriever-dual-match"
    query_text = "experience with distributed systems and kubernetes"
    other_text = "baking bread and gardening tips for beginners"

    embedder = get_embedder()
    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")

    query_dense = (await embedder.embed_dense([query_text]))[0]
    query_sparse = (await embedder.embed_sparse([query_text]))[0]
    other_dense = (await embedder.embed_dense([other_text]))[0]
    other_sparse = (await embedder.embed_sparse([other_text]))[0]

    # "both": matches the query exactly in BOTH dense and sparse space.
    await dense_store.upsert(namespace, [VectorRecord(id="both", values=query_dense)])
    await sparse_store.upsert(
        namespace,
        [
            VectorRecord(
                id="both",
                values=[],
                sparse_indices=query_sparse.indices,
                sparse_values=query_sparse.values,
            )
        ],
    )

    # "dense_only": matches densely, unrelated sparsely.
    await dense_store.upsert(namespace, [VectorRecord(id="dense_only", values=query_dense)])
    await sparse_store.upsert(
        namespace,
        [
            VectorRecord(
                id="dense_only",
                values=[],
                sparse_indices=other_sparse.indices,
                sparse_values=other_sparse.values,
            )
        ],
    )

    # "sparse_only": matches sparsely, unrelated densely.
    await dense_store.upsert(namespace, [VectorRecord(id="sparse_only", values=other_dense)])
    await sparse_store.upsert(
        namespace,
        [
            VectorRecord(
                id="sparse_only",
                values=[],
                sparse_indices=query_sparse.indices,
                sparse_values=query_sparse.values,
            )
        ],
    )

    # "neither": unrelated in both spaces.
    await dense_store.upsert(namespace, [VectorRecord(id="neither", values=other_dense)])
    await sparse_store.upsert(
        namespace,
        [
            VectorRecord(
                id="neither",
                values=[],
                sparse_indices=other_sparse.indices,
                sparse_values=other_sparse.values,
            )
        ],
    )

    results = await hybrid_search(namespace, query_text, top_k=10, final_k=10)
    ids_in_order = [r.id for r in results]

    assert ids_in_order[0] == "both"
    assert set(ids_in_order[:3]) == {"both", "dense_only", "sparse_only"}
    assert ids_in_order.index("neither") > ids_in_order.index("dense_only")
    assert ids_in_order.index("neither") > ids_in_order.index("sparse_only")


@pytest.mark.asyncio
async def test_hybrid_search_respects_final_k_truncation() -> None:
    namespace = "dev-test-retriever-final-k"
    query_text = "python fastapi backend"

    embedder = get_embedder()
    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")

    for i in range(5):
        text = f"{query_text} variant {i}"
        dense_vec = (await embedder.embed_dense([text]))[0]
        sparse_vec = (await embedder.embed_sparse([text]))[0]
        await dense_store.upsert(namespace, [VectorRecord(id=f"c{i}", values=dense_vec)])
        await sparse_store.upsert(
            namespace,
            [
                VectorRecord(
                    id=f"c{i}",
                    values=[],
                    sparse_indices=sparse_vec.indices,
                    sparse_values=sparse_vec.values,
                )
            ],
        )

    results = await hybrid_search(namespace, query_text, top_k=10, final_k=2)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_hybrid_search_metadata_is_passed_through_from_vector_store() -> None:
    namespace = "dev-test-retriever-metadata"
    query_text = "evidence of RAG pipeline work"

    embedder = get_embedder()
    dense_store = get_vector_store("dense")
    sparse_store = get_vector_store("sparse")

    dense_vec = (await embedder.embed_dense([query_text]))[0]
    sparse_vec = (await embedder.embed_sparse([query_text]))[0]
    await dense_store.upsert(
        namespace, [VectorRecord(id="chunk1", values=dense_vec, metadata={"section": "experience"})]
    )
    await sparse_store.upsert(
        namespace,
        [
            VectorRecord(
                id="chunk1",
                values=[],
                sparse_indices=sparse_vec.indices,
                sparse_values=sparse_vec.values,
                metadata={"section": "experience"},
            )
        ],
    )

    results = await hybrid_search(namespace, query_text, top_k=5, final_k=5)

    assert len(results) == 1
    assert results[0].id == "chunk1"
    # Metadata is a convenience copy — callers must NOT treat this as
    # citation-ready; this test only verifies plumbing, not RetrievedMatch's
    # documented invariant (see retriever.py's docstring).
    assert results[0].metadata.get("section") == "experience"

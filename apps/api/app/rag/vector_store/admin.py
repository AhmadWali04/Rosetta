"""Control-plane index administration (create / check existence of the two
serverless indexes) — the one Pinecone concern that has no place in the
`VectorStore` interface at all, since `VectorStore` only models namespace/
vector-level operations (upsert, query, fetch, delete, list, count), never
"does this index exist" or "create this index".

This lives in `app/rag/vector_store/` rather than in `app/rag/indexer.py`
(where the task brief for this module originally asked for this logic)
specifically so AGENTS.md invariant 8 — "Only app/rag/vector_store/ and
app/rag/embeddings.py import the Pinecone SDK" — stays literally true.
`app/rag/indexer.py` calls `ensure_serverless_indexes()` below and never
imports `pinecone` itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pinecone import Pinecone, ServerlessSpec

from app.config import get_settings


def _ensure_serverless_indexes_sync() -> dict[str, str]:
    """Blocking: create the dense + sparse serverless indexes if they don't
    already exist (PRD §8.2: AWS `us-east-1`, dense=cosine, sparse=dotproduct).
    Runs inside `asyncio.to_thread` — see `ensure_serverless_indexes`.
    """
    settings = get_settings()
    client = Pinecone(api_key=settings.pinecone_api_key)

    specs: list[tuple[str, str, str, int | None]] = [
        (settings.pinecone_dense_index, "dense", "cosine", settings.embedding_dimension),
        (settings.pinecone_sparse_index, "sparse", "dotproduct", None),
    ]

    summary: dict[str, str] = {}
    for name, vector_type, metric, dimension in specs:
        if client.has_index(name):
            summary[name] = "already_existed"
            continue

        kwargs: dict[str, Any] = {
            "name": name,
            "vector_type": vector_type,
            "metric": metric,
            "spec": ServerlessSpec(cloud="aws", region="us-east-1"),
            "deletion_protection": "disabled",
        }
        if dimension is not None:
            kwargs["dimension"] = dimension
        client.create_index(**kwargs)
        summary[name] = "created"

    return summary


async def ensure_serverless_indexes() -> dict[str, str]:
    """Async wrapper: idempotently create `settings.pinecone_dense_index`
    (dense, cosine, dimension=`settings.embedding_dimension`) and
    `settings.pinecone_sparse_index` (sparse, dotproduct) if either is
    missing. Returns `{index_name: "created" | "already_existed"}`.
    """
    return await asyncio.to_thread(_ensure_serverless_indexes_sync)

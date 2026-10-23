"""Public surface of the vector store layer. Everything else in the codebase
imports from `app.rag.vector_store` and never reaches into a backend module
directly (AGENTS.md invariant 8: only this package and `app.rag.embeddings`
import the Pinecone SDK).
"""

from __future__ import annotations

from app.rag.vector_store.base import ScoredMatch, VectorRecord, VectorStore
from app.rag.vector_store.factory import get_vector_store

__all__ = [
    "ScoredMatch",
    "VectorRecord",
    "VectorStore",
    "get_vector_store",
]

"""`VectorStore` backend for Pinecone Local, the Docker emulator (PRD §8.8,
AGENTS.md `make up-offline`). Used for integration tests and the offline
demo mode; data lives only in the emulator's memory and is lost on restart
(`make seed` re-runs after each restart per PRD §8.8).

Connection pattern verified against Pinecone's official "Local development
with Pinecone Local" walkthrough (docs.pinecone.io/guides/operations/local-development):
Pinecone Local does not authenticate requests (API keys are ignored - the
docs' own example passes the literal placeholder `"pclocal"`), and because
there's no real control-plane DNS entry for the emulator, the client is
pointed at it directly via `host=` instead of relying on account-based
discovery. From there, index creation and host resolution go through the
same `Pinecone` client calls as real Pinecone (`create_index`/`has_index`/
`describe_index`), which is what lets `app/rag/indexer.py`'s
`ensure_indexes()` work unmodified against either backend.

CAVEAT (flagged per the task spec rather than silently assumed): Pinecone
Local can run in two modes - a "database emulator" mode (indexes created at
runtime via the control-plane API, same flow as real Pinecone - what this
class assumes, and what `make pinecone-init` / `ensure_indexes()` implies
for this project) or an "index emulator" mode (fixed indexes baked in at
container startup via env vars, each on its own port, with no control-plane
index management available at all). If `docker-compose.yml`'s
`pinecone-local` service (owned by another agent) ends up configured for
index-emulator mode, the `describe_index` call below will fail and this
constructor needs to target `host` directly per index instead. Verify
against the final `docker-compose.yml` before relying on this in CI.
"""

from __future__ import annotations

from typing import Any

from pinecone import Pinecone

from app.config import get_settings
from app.rag.vector_store._pinecone_shared import PineconeSDKVectorStore


class PineconeLocalVectorStore(PineconeSDKVectorStore):
    """Wraps one index (dense or sparse) hosted by Pinecone Local."""

    def __init__(self, index_name: str, host: str) -> None:
        super().__init__()
        settings = get_settings()
        self._vector_type = "sparse" if index_name == settings.pinecone_sparse_index else "dense"
        self._index_name = index_name
        self._host = host

    def _build_index(self) -> Any:
        """Blocking: resolve this index's own host and build an `Index`
        handle. Called lazily via `_get_index()` (see `_pinecone_shared.py`'s
        "CORRECTNESS FIX" note) rather than eagerly in `__init__`, since
        this does a real network round-trip (`describe_index`).

        API key value is ignored by Pinecone Local but still required by
        the SDK's constructor; `"pclocal"` matches Pinecone's own example.
        Resolving the per-index host via `describe_index(name=...).host` ->
        `Index(host=...)` matches the official Pinecone Local walkthrough —
        see the module docstring's caveat about emulator modes.
        """
        client = Pinecone(api_key="pclocal", host=self._host)
        index_host = client.describe_index(name=self._index_name).host
        if not index_host:
            raise RuntimeError(
                f"Pinecone Local returned no host for index {self._index_name!r}; "
                "it may not exist yet - run `make pinecone-init` first."
            )
        return client.Index(host=index_host)

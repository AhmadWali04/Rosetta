"""CLI entry point for `make pinecone-init` (PRD §17 M0 / AGENTS.md command
table). Idempotently creates the two serverless indexes (dense + sparse) if
they don't already exist; no-ops for the `memory` backend.

Usage: `cd apps/api && uv run python scripts/pinecone_init.py`
"""

from __future__ import annotations

import asyncio

from app.rag.indexer import ensure_indexes


async def main() -> None:
    summary = await ensure_indexes()

    if "skipped" in summary:
        print(f"Skipped: {summary['skipped']}")
        return

    print("Pinecone index check complete:")
    for index_name, status in summary.items():
        print(f"  - {index_name}: {status}")


if __name__ == "__main__":
    asyncio.run(main())

"""Sync SQLAlchemy session factory (AGENTS.md repo layout: `app/db/`).

Mirrors the exact engine/session pattern already established in
`scripts/seed.py` (M0) — `create_engine(get_settings().database_url,
future=True)` plus a `sessionmaker` with `expire_on_commit=False` — rather
than inventing a second convention for M1.

Intake-graph nodes and the worker run inside a long-lived process, not a
request handler, so blocking sync DB calls are fine here; no async DB
driver is introduced for M1 (per this milestone's task brief).

Two entry points, both built on the same generator:

- `get_session()` — a plain generator function, the shape FastAPI's own
  docs use for a "dependency with yield". Routes use
  `Depends(get_session)`; FastAPI drives the try/finally itself.
- `session_scope()` — `get_session` wrapped in `contextlib.contextmanager`,
  for non-request code (graph nodes, the worker, scripts) that wants
  `with session_scope() as session: ...` instead of manually advancing a
  generator. Both wrap the exact same body, so there is exactly one place
  that opens/closes a `Session`.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI-style dependency-with-yield: `Depends(get_session)` in
    routes. Non-request code should use `session_scope()` below instead of
    calling this directly."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Context-manager-ish helper for non-request code (graph nodes, worker,
# scripts): `with session_scope() as session: ...`. Built from the same
# generator as `get_session()` so there's a single source of truth for the
# open/close lifecycle.
session_scope = contextmanager(get_session)

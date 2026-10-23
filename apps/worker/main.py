"""Worker entrypoint: a simple polling loop over the intake graph.

PRD §13 keeps the stack to "a background worker," deliberately not a task
queue (Celery/Redis) — this loop design is final for the whole project,
not a placeholder. Each iteration's actual work lives in
`process_pending_applications` (runner.py), which is unit-tested directly;
this file only adds the sleep-forever shell and top-level crash isolation
so one bad iteration can't kill the process.
"""

from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.db.session import SessionLocal
from app.graphs.intake.graph import ensure_checkpointer_schema

from runner import process_pending_applications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


def _run_once() -> None:
    db = SessionLocal()
    try:
        process_pending_applications(db)
    finally:
        db.close()


def main() -> None:
    settings = get_settings()
    logger.info("worker starting, poll interval %.1fs", settings.worker_poll_interval_s)
    # One-time, not per-invocation: creates the checkpointer's own tables
    # (`checkpoints`, etc.) if they don't exist yet. Must run before the
    # first graph.invoke(), which otherwise fails with
    # psycopg.errors.UndefinedTable: relation "checkpoints" does not exist.
    ensure_checkpointer_schema(settings.database_url)
    while True:
        try:
            _run_once()
        except Exception:
            logger.exception("worker iteration failed")
        time.sleep(settings.worker_poll_interval_s)


if __name__ == "__main__":
    main()

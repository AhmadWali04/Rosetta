"""The single-iteration worker body: claim every `Application` currently
`status == "submitted"` and run it through the intake graph.

Split out of apps/worker/main.py's infinite polling loop specifically so
it's unit-testable (the loop itself — sleep-forever — isn't something
pytest should exercise). apps/worker is a sibling of apps/api, not part of
the installed `app` package; it runs as a bare script in the worker
container (docker-compose.yml: `python /worker/main.py`, with
./apps/worker bind-mounted to /worker), so this module's own directory is
always on sys.path[0] wherever it runs — including under pytest, once
tests/conftest.py puts apps/worker on sys.path the same way.

Contract for `run_intake_graph`: `(application_id: str, job_id: str,
resume_path: str) -> None`. This is Agent D's expected entry point from
`app.graphs.intake.graph` (apps/api/app/graphs/intake/graph.py) — written
against that expected name/signature; verify once that module lands in
case the real signature differs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.db.models import Application, Event
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("worker")

IntakeGraphRunner = Callable[[str, str, str], None]


def _default_intake_runner() -> IntakeGraphRunner:
    """Resolves Agent D's intake graph entry point.

    Imported lazily (only when actually needed, not at module import time)
    so this module — and the rest of the worker — stays importable and
    testable even before `app.graphs.intake.graph` exists. Callers that
    want to test `process_pending_applications` without the real graph
    should pass `run_intake_graph=<fake>` explicitly instead of relying on
    this resolving anything.
    """
    from app.graphs.intake.graph import run_intake_graph

    return run_intake_graph


def process_pending_applications(
    db: Session, run_intake_graph: IntakeGraphRunner | None = None
) -> None:
    """Claims and processes every submitted application, oldest first.

    Each row is claimed (status -> "analyzing") and committed *before* the
    intake graph runs, so a crash or restart mid-batch never reprocesses an
    application that's already underway. A failure in one application's
    graph run is caught here and turned into `status="intake_failed"` plus
    an audit `Event` row — it must never abort the rest of the batch or
    crash the caller's polling loop (AGENTS.md invariant #4: audit
    everything).
    """
    runner = run_intake_graph or _default_intake_runner()

    rows = (
        db.execute(
            select(Application)
            .where(Application.status == "submitted")
            .order_by(Application.created_at)
        )
        .scalars()
        .all()
    )

    for row in rows:
        row.status = "analyzing"
        db.commit()

        try:
            runner(row.id, row.job_id, row.resume_path)
        except Exception as exc:
            row.status = "intake_failed"
            db.add(
                Event(
                    application_id=row.id,
                    actor="system",
                    action="intake_failed",
                    payload={"error": str(exc)},
                )
            )
            db.commit()
            logger.exception("intake graph failed for application %s", row.id)

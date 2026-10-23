"""Claim one durable Copilot job per poll and execute outside HTTP requests."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.copilot import CopilotRun
from app.graphs.state import CopilotResult, CopilotState
from app.services.copilot import SAFE_FAILURE, audit_run, get_run

logger = logging.getLogger("worker.copilot")
GraphRunner = Callable[[CopilotState, bool | None], CopilotResult]


def _default_runner() -> GraphRunner:
    from app.graphs.copilot.graph import run_copilot_graph

    return run_copilot_graph


def process_pending_copilot(db: Session, run_graph: GraphRunner | None = None) -> bool:
    """SKIP LOCKED plus committed running status prevents duplicate execution.

    Human confirmations queue the same run/checkpoint once. Process crashes
    leave a visible running row rather than retrying a possibly committed
    write without human intervention. Graph errors never escape this poll.
    """
    run = db.scalar(
        select(CopilotRun)
        .where(CopilotRun.status == "queued")
        .order_by(CopilotRun.created_at, CopilotRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if run is None:
        return False
    run_id = run.id
    run.status = "running"
    audit_run(db, run, "copilot_started", payload={"resuming": run.confirmation is not None})
    db.commit()
    state = CopilotState(run_id=run.id, job_id=run.job_id, scope=run.scope, message=run.message)
    try:
        runner = run_graph or _default_runner()
        result = runner(state, run.confirmation)
        if result.run_id != run_id:
            raise ValueError("graph result belongs to a different run")
        if result.needs_confirmation and (result.proposal is None or run.confirmation is not None):
            raise ValueError("unexpected confirmation result")
        run = get_run(db, run_id, lock=True)
        run.result = result.model_dump()
        run.status = "awaiting_confirmation" if result.needs_confirmation else "completed"
        run.error = None
        audit_run(
            db,
            run,
            "copilot_awaiting_confirmation" if result.needs_confirmation else "copilot_completed",
            payload={
                "route": result.route,
                "retries": result.retries,
                "steps": result.steps,
            },
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a failed graph must not terminate the worker
        db.rollback()
        run = get_run(db, run_id, lock=True)
        run.status = "failed"
        run.error = SAFE_FAILURE
        run.result = None
        audit_run(db, run, "copilot_failed", payload={"error": SAFE_FAILURE})
        db.commit()
        # Exception messages may contain provider payloads or credentials.
        logger.error("copilot run failed run_id=%s exception_type=%s", run_id, type(exc).__name__)
    return True

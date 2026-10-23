"""Persist node (PRD §7.1 final step, the flow diagram's trailing
`H[(Persist profile)]`).

Kept as its own file rather than folded into Agent D's `hr_explainer.py`
so the DB-write step is independently unit-testable, matching the PRD's
explicit "...then Persist" framing of the pipeline.

Updates the profile in place, then normalizes component-backed scores across
the job pool in the same transaction. Returns the committed values to graph
state, and audits score changes plus intake completion. Job-first locking
matches HR mutations. New intakes become analyzed; reruns preserve human
decisions. Vector status remains owned by chunk_and_index.

`async def`, matching every other node in this package (see
`ingest_parse.py`'s docstring) — trivially so here, since this node's own
body has no awaited calls at all.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Application, Event, Job, Profile
from app.db.session import session_scope
from app.graphs.state import IntakeState
from app.services.pool_scoring import recompute_pool


async def persist(state: IntakeState) -> dict[str, Any]:
    skills_json = [s.model_dump() for s in state.normalized_skills]
    requirement_matches_json = [m.model_dump() for m in state.requirement_matches]

    with session_scope() as session:
        application = session.get(Application, state.application_id)
        if application is None:
            raise ValueError(f"persist: no Application row for id={state.application_id!r}")

        if application.job_id != state.job_id:
            raise ValueError("persist: application does not belong to the graph's job")
        # Always job -> application -> profile, matching HR decisions/promotion.
        # No writes/flushes may happen before the job lock is acquired.
        job = session.scalar(select(Job).where(Job.id == state.job_id).with_for_update())
        if job is None:
            raise ValueError(f"persist: no Job row for id={state.job_id!r}")
        application = session.scalar(
            select(Application)
            .where(Application.id == state.application_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if application is None:
            raise ValueError("persist: application disappeared before persistence")
        profile = session.get(Profile, state.application_id)
        if profile is None:
            profile = Profile(application_id=state.application_id)
            session.add(profile)
        profile.skills = skills_json
        profile.requirement_matches = requirement_matches_json
        profile.score = state.score
        profile.recommendation = state.recommendation
        profile.confidence = state.confidence
        profile.flags = list(state.flags)
        profile.explanation = state.explanation
        profile.score_components = (
            state.score_components.model_dump() if state.score_components is not None else None
        )
        # A retry must never undo an HR/Tech Lead decision.
        if application.status in {"submitted", "analyzing", "intake_failed"}:
            application.status = "analyzed"
        session.flush()
        recompute_pool(session, state.job_id, get_settings())
        session.add(
            Event(
                application_id=state.application_id,
                actor="system",
                action="intake_complete",
                payload={
                    "score": profile.score,
                    "recommendation": profile.recommendation,
                    "confidence": profile.confidence,
                },
            )
        )
        session.commit()
        return {
            "score": profile.score,
            "recommendation": profile.recommendation,
            "confidence": profile.confidence,
        }

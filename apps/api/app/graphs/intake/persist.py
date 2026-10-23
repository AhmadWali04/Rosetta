"""Persist node (PRD §7.1 final step, the flow diagram's trailing
`H[(Persist profile)]`).

Kept as its own file rather than folded into Agent D's `hr_explainer.py`
so the DB-write step is independently unit-testable, matching the PRD's
explicit "...then Persist" framing of the pipeline.

Writes the final `Profile` row, flips `Application.status` to `analyzed`,
and writes the closing `intake_complete` audit event (AGENTS.md invariant
#4: audit everything). Does not touch `vector_status` (owned by
`chunk_and_index`) and does not add to `flags` (accumulated upstream by
`sanitize`/`chunk_and_index`/the LLM nodes) — this node persists whatever
`state` already holds, it doesn't decide anything new.

If a `Profile` row already exists for this application (e.g. a graph
re-run / retry), it is replaced rather than left to raise an integrity
error on the primary-key insert — `application_id` is the `Profile`
primary key (graphs/state.py / db/models.py), so re-running intake for the
same application must overwrite, not duplicate.

`async def`, matching every other node in this package (see
`ingest_parse.py`'s docstring) — trivially so here, since this node's own
body has no awaited calls at all.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Application, Event, Profile
from app.db.session import session_scope
from app.graphs.state import IntakeState


async def persist(state: IntakeState) -> dict[str, Any]:
    skills_json = [s.model_dump() for s in state.normalized_skills]
    requirement_matches_json = [m.model_dump() for m in state.requirement_matches]

    with session_scope() as session:
        application = session.get(Application, state.application_id)
        if application is None:
            raise ValueError(f"persist: no Application row for id={state.application_id!r}")

        existing = session.get(Profile, state.application_id)
        if existing is not None:
            session.delete(existing)
            session.flush()

        session.add(
            Profile(
                application_id=state.application_id,
                skills=skills_json,
                requirement_matches=requirement_matches_json,
                score=state.score,
                recommendation=state.recommendation,
                confidence=state.confidence,
                flags=list(state.flags),
                explanation=state.explanation,
            )
        )
        application.status = "analyzed"
        session.add(
            Event(
                application_id=state.application_id,
                actor="system",
                action="intake_complete",
                payload={
                    "score": state.score,
                    "recommendation": state.recommendation,
                    "confidence": state.confidence,
                },
            )
        )
        session.commit()

    return {}

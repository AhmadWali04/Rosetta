"""PRD §7.1 HR Explainer node.

One LLM call, grounded ONLY in `state.requirement_matches` (status +
rationale + the already-validated `resolved_chunk_ids` — never new chunk
text, never a new citation). The one extra piece of context pulled in here
is each requirement's own `text` from Postgres `jd_requirements` — that's
read-only hydration of a fact already fixed earlier in the pipeline (which
requirement this status belongs to), not a new claim about the candidate,
so it doesn't weaken the "never invent new citations or claims" rule the
task brief sets for this node.

Produces plain-English, per-requirement rationale for a non-technical
reader (PRD F2.2's example: "FastAPI is a Python backend framework — this
satisfies 'backend frameworks such as Node.js or FastAPI'") plus one
overall paragraph. `state.py`'s `explanation` field is a single `str`, so
the structured `{per_requirement, overall}` result is serialized as a JSON
string into that field — the HR portal (M2) is expected to
`JSON.parse`/`json.loads` it back out rather than render it as raw prose.

Depends on, and confirmed against, Agent A's `app.llm.get_llm_provider`
and Agent C's `app.db.session.session_scope`.

Sync, matching the convention `graph.py` settled on for the whole intake
graph. The async LLM call is bridged with a single `asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import JdRequirement
from app.db.session import session_scope
from app.graphs.state import IntakeState
from app.llm import get_llm_provider
from app.prompts import load_prompt

# Agent A's versioned system prompt (app/prompts/hr_explainer.v1.md) -
# confirmed landed. It's written for one requirement per call; this node
# batches every requirement into one call instead (matching the task
# brief's `per_requirement: dict[str, str]` + `overall: str` output shape),
# so the user-turn prompt built in `_build_prompt` adapts the template's
# single-requirement framing into one block per requirement, each still
# following the template's own rules (explain the given status, don't
# re-judge it, never introduce an uncited claim).
_SYSTEM_PROMPT = load_prompt("hr_explainer.v1")


class RequirementExplanation(BaseModel):
    requirement_id: str
    explanation: str


class HrExplanationResult(BaseModel):
    # A list of {requirement_id, explanation}, NOT dict[str, str] — an
    # open-ended dict's JSON schema (`additionalProperties`) is rejected by
    # Gemini's Developer API free tier ("additionalProperties is only
    # supported in Gemini Enterprise Agent Platform mode"), confirmed live
    # against the real API, not assumed from docs. OpenAI's structured
    # outputs have the same restriction in strict mode (a fixed/enumerable
    # property set, no truly dynamic keys) — this was a latent bug for
    # OpenAI too, just never exercised live before OpenAI credits ran out.
    # Converted back to the dict shape `app/services/hr.py` already expects
    # in `_hr_explainer_async` below, before it's serialized/persisted —
    # this is purely an LLM-output-schema fix, not a stored-data-shape change.
    per_requirement: list[RequirementExplanation] = Field(default_factory=list)
    overall: str = ""


def _fetch_requirement_texts(session: Session, requirement_ids: list[str]) -> dict[str, str]:
    if not requirement_ids:
        return {}
    rows = session.query(JdRequirement).filter(JdRequirement.id.in_(requirement_ids)).all()
    return {row.id: row.text for row in rows}


def _build_prompt(state: IntakeState, requirement_text_by_id: dict[str, str]) -> str:
    # `rationale` may reference/paraphrase candidate resume text (it was
    # produced by the Requirement Matcher from cited chunks), so it's
    # wrapped in the same <untrusted_resume_text> delimiter
    # app/prompts/hr_explainer.v1.md documents - the requirement text and
    # status are trusted system data and stay outside it.
    lines = [f"Candidate application: {state.application_id}", "Requirements:"]
    for match in state.requirement_matches:
        req_text = requirement_text_by_id.get(match.requirement_id, "(unknown requirement)")
        lines.append(
            f'- requirement_id="{match.requirement_id}" text="{req_text}" '
            f'status="{match.status}" cited_evidence_count={len(match.resolved_chunk_ids)}\n'
            "  <untrusted_resume_text>\n"
            f"  {match.rationale}\n"
            "  </untrusted_resume_text>"
        )
    return "\n".join(lines)


async def _explain(
    state: IntakeState, requirement_text_by_id: dict[str, str]
) -> HrExplanationResult:
    settings = get_settings()
    provider = get_llm_provider()
    return await provider.generate_structured(
        system=_SYSTEM_PROMPT,
        prompt=_build_prompt(state, requirement_text_by_id),
        output_model=HrExplanationResult,
        temperature=settings.llm_temperature,
    )


def hr_explainer(state: IntakeState) -> dict[str, Any]:
    """Node function: `(IntakeState) -> partial state update`. Sync entry
    point; the async LLM call is bridged with one `asyncio.run(...)`."""
    return asyncio.run(_hr_explainer_async(state))


async def _hr_explainer_async(state: IntakeState) -> dict[str, Any]:
    if not state.requirement_matches:
        payload = {"per_requirement": {}, "overall": "No requirements were evaluated."}
        return {"explanation": json.dumps(payload)}

    requirement_ids = [m.requirement_id for m in state.requirement_matches]
    with session_scope() as session:
        requirement_text_by_id = _fetch_requirement_texts(session, requirement_ids)

    result = await _explain(state, requirement_text_by_id)

    # Grounding filter: drop any per_requirement entry that doesn't
    # correspond to a requirement_id we actually evaluated — an invented
    # entry would be a claim about a requirement that was never matched,
    # which the module docstring's "never invent new ... claims" explicitly
    # rules out. Also converts the LLM's list-of-objects output shape back
    # into the dict shape `app/services/hr.py` expects in the persisted
    # `explanation` JSON (see `HrExplanationResult`'s docstring for why the
    # LLM-facing shape differs from the stored shape).
    valid_ids = set(requirement_ids)
    per_requirement = {
        item.requirement_id: item.explanation
        for item in result.per_requirement
        if item.requirement_id in valid_ids
    }

    payload = {"per_requirement": per_requirement, "overall": result.overall}
    return {"explanation": json.dumps(payload)}

"""Grounding gate: scope-check every citation against current Postgres rows."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.graphs.state import CopilotState
from app.tools.copilot import validate_citations


def grounding(state: CopilotState) -> dict[str, Any]:
    cited = [chunk_id for claim in state.claims for chunk_id in claim.chunk_ids]
    provided = {citation.chunk_id for citation in state.evidence}
    scope = "pool" if state.route == "similar" else state.scope
    resolved = validate_citations(state.job_id, scope, [key for key in cited if key in provided])
    valid = {citation.chunk_id for citation in resolved}
    owner_by_id = {citation.chunk_id: citation.application_id for citation in resolved}
    supported = []
    for claim in state.claims:
        if not claim.chunk_ids or not set(claim.chunk_ids) <= valid:
            continue
        owners = {owner_by_id[chunk_id] for chunk_id in claim.chunk_ids}
        if state.route in {"compare", "similar"}:
            if len(owners) < 2:
                continue
            if state.route == "similar":
                selected = (
                    state.scope.split(":", 1)[1] if state.scope.startswith("candidate:") else None
                )
                if selected is None or selected not in owners:
                    continue
        supported.append(claim)
    grounded = len(supported) == len(state.claims)
    warnings = list(state.warnings)
    explanation = state.explanation if state.route in {"explain", "similar"} else ""
    retries = state.retries
    if not grounded:
        warnings.append("Grounding rejected claims without valid scoped resume citations.")
        if retries < get_settings().copilot_max_grounding_retries:
            retries += 1
        else:
            grounded = True
            explanation = (
                "Couldn't verify every claim from the resume evidence. "
                "Unsupported claims were omitted."
            )
    elif not supported and state.route != "explain":
        explanation = explanation or "Couldn't verify this from the available resume evidence."
    accepted_ids = {key for claim in supported for key in claim.chunk_ids}
    resolved = [citation for citation in resolved if citation.chunk_id in accepted_ids]
    return {
        "claims": supported if grounded else state.claims,
        "evidence": resolved if grounded else state.evidence,
        "grounded": grounded,
        "retries": retries,
        "warnings": list(dict.fromkeys(warnings)),
        "explanation": explanation,
        "steps": [*state.steps, "grounding_check"],
    }

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
    supported = [claim for claim in state.claims if claim.chunk_ids and set(claim.chunk_ids) <= valid]
    grounded = len(supported) == len(state.claims)
    warnings = list(state.warnings)
    explanation = state.explanation if state.route == "explain" else ""
    retries = state.retries
    if not grounded:
        warnings.append("Grounding rejected claims without valid scoped resume citations.")
        if retries < get_settings().copilot_max_grounding_retries:
            retries += 1
        else:
            grounded = True
            explanation = "Couldn't verify every claim from the resume evidence. Unsupported claims were omitted."
    elif not supported and state.route != "explain":
        explanation = "Couldn't verify this from the available resume evidence."
    return {"claims": supported if grounded else state.claims,
            "evidence": resolved if grounded else state.evidence,
            "grounded": grounded, "retries": retries, "warnings": list(dict.fromkeys(warnings)),
            "explanation": explanation, "steps": [*state.steps, "grounding_check"]}

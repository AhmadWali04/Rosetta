"""Gather bounded job/candidate-scoped resume evidence for the selected agent."""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.graphs.state import CopilotCitation, CopilotState
from app.tools import copilot as tools


def gather(state: CopilotState) -> dict[str, Any]:
    if state.scope != "pool" and not state.scope.startswith("candidate:"):
        raise ValueError("Invalid copilot scope")
    evidence: list[CopilotCitation] = []
    warnings = list(state.warnings)
    if state.scope.startswith("candidate:"):
        candidate_id = state.scope.split(":", 1)[1]
        tools.get_candidate_profile(state.job_id, candidate_id)
        ids = [candidate_id]
        if state.route == "similar":
            similar, messages = tools.find_similar(state.job_id, candidate_id)
            ids.extend(similar)
            warnings.extend(messages)
    else:
        ids = [str(row["id"]) for row in tools.rank_pool(state.job_id)]
    if state.route not in {"explain", "update_status"}:
        for candidate_id in ids:
            chunks, messages = tools.search_resume_chunks(state.job_id, candidate_id, state.message)
            evidence.extend(chunks)
            warnings.extend(messages)
    # Similar-candidate answers legitimately cite peers in this job, while
    # candidate verification must remain restricted to the selected applicant.
    limit = get_settings().copilot_max_evidence_chunks
    return {"evidence": evidence[:limit], "warnings": list(dict.fromkeys(warnings)),
            "steps": [*state.steps, "gather_evidence"]}

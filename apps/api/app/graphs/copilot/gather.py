"""Gather bounded job/candidate-scoped resume evidence for the selected agent."""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.graphs.state import CopilotCitation, CopilotState
from app.tools import copilot as tools


def gather(state: CopilotState) -> dict[str, Any]:
    if state.scope != "pool" and not state.scope.startswith("candidate:"):
        raise ValueError("Invalid copilot scope")
    evidence: list[CopilotCitation] = []
    warnings = list(state.warnings)
    ranking = (
        tools.rank_pool(state.job_id) if state.scope == "pool" or state.route == "compare" else []
    )
    if state.scope.startswith("candidate:"):
        candidate_id = state.scope.split(":", 1)[1]
        tools.get_candidate_profile(state.job_id, candidate_id)
        ids = [candidate_id]
        if state.route == "similar":
            similar, messages = tools.find_similar(state.job_id, candidate_id)
            ids.extend(similar)
            warnings.extend(messages)
    else:
        ids = [str(row["id"]) for row in ranking]
    limit = get_settings().copilot_max_evidence_chunks
    allowance = max(1, limit // max(1, len(ids)))
    if state.route not in {"explain", "update_status"}:
        for candidate_id in ids:
            chunks, messages = tools.search_resume_chunks(state.job_id, candidate_id, state.message)
            evidence.extend(chunks[:allowance])
            warnings.extend(messages)
    # Similar-candidate answers legitimately cite peers in this job, while
    # candidate verification must remain restricted to the selected applicant.
    fields = (
        "id",
        "score",
        "recommendation",
        "confidence",
        "must_have_met",
        "must_have_total",
        "flags",
    )
    context = json.dumps(
        {
            "jd_requirements": tools.get_jd_requirements(state.job_id),
            "pool_ranking": [{key: row[key] for key in fields if key in row} for row in ranking],
        }
    )
    return {
        "evidence": evidence[:limit],
        "external_context": context,
        "warnings": list(dict.fromkeys(warnings)),
        "steps": [*state.steps, "gather_evidence"],
    }

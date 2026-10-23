"""Result-based GitHub enrichment; never replaces resume citation requirements."""
from __future__ import annotations

import json
from typing import Any

from app.graphs.state import CopilotState
from app.tools.copilot import get_candidate_profile
from app.tools.github import github_profile


def deep_verify(state: CopilotState) -> dict[str, Any]:
    warnings = list(state.warnings)
    context = ""
    if state.scope.startswith("candidate:"):
        profile = get_candidate_profile(state.job_id, state.scope.split(":", 1)[1])
        url = profile.get("links", {}).get("github_url")
        if url:
            try:
                context = json.dumps(github_profile(str(url)))
                warnings.append("GitHub is supplementary public context; resume citations remain required.")
            except Exception:
                warnings.append("GitHub verification unavailable; no external claims were accepted.")
        else:
            warnings.append("No GitHub profile was supplied for Deep Verify.")
    else:
        warnings.append("Deep Verify requires a selected candidate.")
    return {"deep_verified": True, "external_context": context, "warnings": warnings,
            "steps": [*state.steps, "deep_verify"]}

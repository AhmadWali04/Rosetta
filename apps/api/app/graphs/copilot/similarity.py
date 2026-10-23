"""Explain retrieved peers using their Postgres evidence."""

from typing import Any

from app.graphs.copilot.common import generate_answer
from app.graphs.state import CopilotState


def similarity(state: CopilotState) -> dict[str, Any]:
    selected = state.scope.split(":", 1)[1] if state.scope.startswith("candidate:") else None
    owners = {citation.application_id for citation in state.evidence}
    if selected is None or selected not in owners or not owners.difference({selected}):
        warning = "No similar candidate with available resume evidence was found."
        return {
            "claims": [],
            "confidence": 0.0,
            "explanation": warning,
            "warnings": list(dict.fromkeys([*state.warnings, warning])),
            "steps": [*state.steps, "copilot_similar"],
        }
    return generate_answer(state, "copilot_similar.v1")

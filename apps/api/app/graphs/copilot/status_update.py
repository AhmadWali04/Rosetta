"""Human-in-the-loop boundary for the copilot's only write tool."""
from typing import Any

from langgraph.types import interrupt

from app.graphs.state import CopilotState
from app.tools.copilot import update_status


def status_update(state: CopilotState) -> dict[str, Any]:
    if state.proposal is None:
        raise ValueError("No status change proposal")
    decision = interrupt(state.proposal.model_dump())
    if decision is True:
        update_status(state.job_id, state.proposal, confirmed=True)
        explanation = "The HR-confirmed status change was recorded in the audit log."
    else:
        explanation = "Status change cancelled; no candidate status was changed."
    return {"explanation": explanation, "claims": [], "evidence": [], "grounded": True,
            "steps": [*state.steps, "human_confirmation"]}

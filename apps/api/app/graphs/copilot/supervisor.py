"""Request-based routing, revisited after grounding failures."""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.graphs.copilot.common import RouteDecision, data_block
from app.graphs.state import CopilotProposal, CopilotState
from app.llm import get_llm_provider
from app.prompts import load_prompt


def supervisor(state: CopilotState) -> dict[str, Any]:
    decision = asyncio.run(get_llm_provider().generate_structured(
        system=load_prompt("copilot_supervisor.v1"),
        prompt=data_block("user_request", state.message) + f"\nScope: {state.scope}\n"
        + f"Grounding retries: {state.retries}; answer only with resolved resume citations.",
        output_model=RouteDecision, temperature=get_settings().llm_temperature))
    route = decision.route
    warnings = list(state.warnings)
    proposal = None
    if route == "update_status":
        if not state.scope.startswith("candidate:") or decision.status is None:
            route = "verify"
            warnings.append("Status changes require a selected candidate and an explicit label.")
        else:
            proposal = CopilotProposal(application_id=state.scope.split(":", 1)[1],
                                       status=decision.status,
                                       reason="HR requested this status change through the copilot.")
    return {"route": route, "proposal": proposal, "claims": [], "grounded": False,
            "warnings": warnings, "steps": [*state.steps, "supervisor"]}

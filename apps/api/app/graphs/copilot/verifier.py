"""Evidence verification; its confidence drives the Deep Verify branch."""
from typing import Any

from app.graphs.copilot.common import generate_answer
from app.graphs.state import CopilotState


def verifier(state: CopilotState) -> dict[str, Any]:
    return generate_answer(state, "copilot_verify.v1")

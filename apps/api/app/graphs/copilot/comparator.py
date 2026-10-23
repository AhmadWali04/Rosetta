"""Compare candidate evidence without treating scores as supporting citations."""

from typing import Any

from app.graphs.copilot.common import generate_answer
from app.graphs.state import CopilotState


def comparator(state: CopilotState) -> dict[str, Any]:
    return generate_answer(state, "copilot_compare.v1")

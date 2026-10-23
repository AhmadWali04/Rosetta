"""Targeted screening questions anchored to resume evidence."""

from typing import Any

from app.graphs.copilot.common import generate_answer
from app.graphs.state import CopilotState


def questions(state: CopilotState) -> dict[str, Any]:
    return generate_answer(state, "copilot_questions.v1")

"""Pydantic state models shared by graphs. M0 placeholder shape only — node
logic and the full field set land in M1 (intake) and M3 (copilot). Kept here
so M1+ don't invent a second state convention.
"""

from __future__ import annotations

from pydantic import BaseModel


class IntakeState(BaseModel):
    """State threaded through graphs/intake. One field per node's output,
    added as each node lands in M1."""

    application_id: str
    job_id: str
    resume_path: str
    flags: list[str] = []


class CopilotState(BaseModel):
    """State threaded through graphs/copilot. Added to in M3."""

    scope: str  # "candidate:<application_id>" | "pool"
    message: str
    retries: int = 0

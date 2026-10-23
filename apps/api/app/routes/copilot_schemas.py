"""Public queued/SSE Copilot contracts; frontend types are generated from these."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.graphs.state import CopilotResult

RunStatus = Literal["queued", "running", "awaiting_confirmation", "completed", "failed"]


class CopilotRequest(BaseModel):
    job_id: str = Field(min_length=1)
    scope: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("scope")
    @classmethod
    def valid_scope(cls, value: str) -> str:
        if value != "pool" and not (value.startswith("candidate:") and value[10:].strip()):
            raise ValueError("scope must be pool or candidate:<application_id>")
        return value

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class CopilotConfirmation(BaseModel):
    approve: bool


class CopilotRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    scope: str
    message: str
    status: RunStatus
    result: CopilotResult | None
    error: str | None
    created_at: datetime


class CopilotEvent(BaseModel):
    event: Literal["queued", "progress", "result", "error"]
    run_id: str
    status: RunStatus
    result: CopilotResult | None = None
    error: str | None = None

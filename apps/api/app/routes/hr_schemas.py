"""Generated-client contracts for the M2 human review portal (F2.1–F2.6)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PipelineCandidate(BaseModel):
    id: str
    job_id: str
    name: str
    status: str
    vector_status: str
    created_at: datetime
    score: float | None
    recommendation: str | None
    confidence: float | None
    must_have_met: int
    must_have_total: int
    flags: list[str]


class SkillOut(BaseModel):
    term: str
    canonical: str
    requirement_ids: list[str]
    chunk_ids: list[str]


class RequirementOut(BaseModel):
    id: str
    text: str
    kind: str
    status: str
    explanation: str
    chunk_ids: list[str]


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    section: str
    text: str
    char_start: int
    char_end: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor: str
    action: str
    payload: dict[str, object]
    created_at: datetime


class CandidateDetail(PipelineCandidate):
    skills: list[SkillOut]
    requirements: list[RequirementOut]
    chunks: list[ChunkOut]
    events: list[EventOut]


class StatusChange(BaseModel):
    status: Literal["valid", "pending", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)


class PromotionRequest(BaseModel):
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)


class PromotionConfirm(PromotionRequest):
    application_ids: list[str]


class PromotionPreview(BaseModel):
    job_id: str
    percent: float
    pending_count: int
    application_ids: list[str]
    candidates: list[PipelineCandidate]

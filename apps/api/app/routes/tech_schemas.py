"""Contracts for the M4 Tech Lead portal (F3.1-F3.6). Reuses HR's
`PipelineCandidate`/`CandidateDetail`/`EventOut` shapes directly — the
queue/profile view is the same evidence-linked data, just filtered to
`status="valid"` and with a different action available (invite/decline
+ rubric, not valid/pending/rejected labelling)."""

from pydantic import BaseModel, Field


class RubricScore(BaseModel):
    requirement_id: str
    score: int = Field(ge=1, le=5)


class TechDecision(BaseModel):
    decision: str = Field(pattern="^(invited|rejected)$")
    rubric: list[RubricScore] = Field(default_factory=list)
    overall: float | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)

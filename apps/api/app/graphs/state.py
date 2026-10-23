"""Pydantic state models shared by graphs.

`IntakeState` is fleshed out for real in M1: one field per node's output,
written by exactly one node and read by any node downstream. Sub-models
(`Section`, `ChunkData`, ...) are kept here too so every intake node imports
the same shapes rather than each inventing its own dict keys.

`CopilotState` stays a placeholder — fleshed out in M3.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Section(BaseModel):
    """One heading-delimited region of the resume (PRD §7.1 "section
    segmentation"). `char_start`/`char_end` are offsets into the document's
    full raw text, not the sanitized text — the sanitize node remaps them."""

    name: str
    text: str
    char_start: int
    char_end: int


class ChunkData(BaseModel):
    """One resume chunk, pre-persistence. Mirrors `app.db.models.ResumeChunk`
    minus the DB-assigned `id`; `char_start`/`char_end` are offsets into the
    *sanitized* full text, matching what `resume_chunks` stores (PRD §8.3)."""

    chunk_idx: int
    section: str
    text: str
    char_start: int
    char_end: int
    pinecone_id: str


class ExtractedSkill(BaseModel):
    """PRD §7.1 Skill Extractor output shape."""

    skill: str
    evidence_span: str
    context: str
    recency: str
    depth_signal: str  # "list_only" | "coursework" | "project" | "production"


class NormalizedSkill(BaseModel):
    """PRD §7.1 Skill Normalizer output: an extracted skill mapped to a
    canonical `skill_taxonomy` row, or left unmapped."""

    extracted: ExtractedSkill
    canonical: str | None
    taxonomy_id: str | None


class RequirementMatch(BaseModel):
    """PRD §7.1 Requirement Matcher output. `cited_chunk_ids` are the ONLY
    chunk ids the LLM named; `resolved_chunk_ids` is the subset that
    actually resolved against Postgres `resume_chunks` for this application
    (AGENTS.md invariant #1 — uncited/unresolved claims are dropped, never
    displayed as fact)."""

    requirement_id: str
    status: str  # "met" | "partial" | "missing"
    cited_chunk_ids: list[str] = Field(default_factory=list)
    resolved_chunk_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class IntakeState(BaseModel):
    """State threaded through graphs/intake. One field per node's output,
    in the order the static pipeline (PRD §7.1) produces them:

    Ingest & Parse          -> raw_text, sections
    Sanitize & Injection Check -> sanitized_text, flags
    Chunk & Index           -> chunks, chunk_vectors, summary_vector, vector_status
    Skill Extractor         -> extracted_skills
    Skill Normalizer        -> normalized_skills
    Requirement Matcher     -> requirement_matches
    Scorer                  -> score, recommendation, confidence
    HR Explainer            -> explanation
    """

    application_id: str
    job_id: str
    resume_path: str
    flags: list[str] = Field(default_factory=list)

    raw_text: str = ""
    sections: list[Section] = Field(default_factory=list)

    sanitized_text: str = ""

    chunks: list[ChunkData] = Field(default_factory=list)
    # chunk pinecone_id -> dense vector, kept in-state so the Requirement
    # Matcher can fall back to it directly on a freshness timeout or a
    # failed upsert (PRD §8.5/§8.6) without a second Pinecone round-trip.
    chunk_vectors: dict[str, list[float]] = Field(default_factory=dict)
    summary_vector: list[float] = Field(default_factory=list)
    vector_status: str = "pending"  # pending | indexing | indexed | failed

    extracted_skills: list[ExtractedSkill] = Field(default_factory=list)
    normalized_skills: list[NormalizedSkill] = Field(default_factory=list)
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)

    score: float = 0.0
    recommendation: str = "review"  # advance | review | decline
    confidence: float = 0.0

    explanation: str = ""


class CopilotState(BaseModel):
    """State threaded through graphs/copilot. Added to in M3."""

    scope: str  # "candidate:<application_id>" | "pool"
    message: str
    retries: int = 0

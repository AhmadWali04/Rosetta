"""SQLAlchemy models for every table in PRD §14. Postgres is the source of
truth (AGENTS.md invariant 7) — Pinecone is a derived index rebuildable from
these tables via `make reindex`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    raw_jd: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    applications: Mapped[list[Application]] = relationship(back_populates="job")
    jd_requirements: Mapped[list[JdRequirement]] = relationship(back_populates="job")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    links: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resume_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="submitted")
    vector_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped[Job] = relationship(back_populates="applications")
    profile: Mapped[Profile | None] = relationship(back_populates="application", uselist=False)
    chunks: Mapped[list[ResumeChunk]] = relationship(back_populates="application")
    reviews: Mapped[list[Review]] = relationship(back_populates="application")
    events: Mapped[list[Event]] = relationship(back_populates="application")


class Profile(Base):
    __tablename__ = "profiles"

    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id"), primary_key=True
    )
    skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requirement_matches: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recommendation: Mapped[str] = mapped_column(String, nullable=False, default="review")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    application: Mapped[Application] = relationship(back_populates="profile")


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id"), nullable=False
    )
    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    # pinecone_id = {application_id}#chunk#{n} — no vector column, Pinecone is derived.
    pinecone_id: Mapped[str] = mapped_column(String, nullable=False)
    embed_model: Mapped[str] = mapped_column(String, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    application: Mapped[Application] = relationship(back_populates="chunks")


class JdRequirement(Base):
    __tablename__ = "jd_requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # must_have | nice_to_have
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pinecone_id: Mapped[str] = mapped_column(String, nullable=False)

    job: Mapped[Job] = relationship(back_populates="jd_requirements")


class SkillTaxonomy(Base):
    __tablename__ = "skill_taxonomy"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    canonical: Mapped[str] = mapped_column(String, nullable=False)
    alt_labels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False)  # onet | esco
    pinecone_id: Mapped[str] = mapped_column(String, nullable=False)


class VectorJob(Base):
    """Reindex/delete work log — the outbox for dual-write (PRD §8.5)."""

    __tablename__ = "vector_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    namespace: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # upsert | reindex | delete
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id"), nullable=False
    )
    reviewer_role: Mapped[str] = mapped_column(String, nullable=False)  # hr | tech_lead
    rubric: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    overall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    comments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    application: Mapped[Application] = relationship(back_populates="reviews")


class Event(Base):
    """Audit log — every graph run, label change, override, invite, review
    writes a row here (AGENTS.md invariant 4)."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    application: Mapped[Application] = relationship(back_populates="events")

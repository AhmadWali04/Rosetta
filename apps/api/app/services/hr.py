"""Human review, PostgreSQL citation hydration, and atomic audited decisions."""

import json
import math
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Application, Event, Job
from app.routes.hr_schemas import (
    CandidateDetail,
    ChunkOut,
    EventOut,
    PipelineCandidate,
    PromotionConfirm,
    PromotionPreview,
    RequirementOut,
    SkillOut,
    StatusChange,
)


def _application(db: Session, application_id: str, *, lock: bool = False) -> Application:
    statement = select(Application).where(Application.id == application_id)
    if lock:
        statement = statement.with_for_update()
    application = db.scalar(statement.execution_options(populate_existing=True))
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")
    return application


def _requirements(application: Application) -> list[RequirementOut]:
    profile = application.profile
    matches = {m.get("requirement_id"): m for m in profile.requirement_matches} if profile else {}
    valid_ids = {
        identifier: chunk.id
        for chunk in application.chunks
        for identifier in (chunk.id, chunk.pinecone_id)
    }
    explanations = {}
    if profile:
        try:
            parsed = json.loads(profile.explanation)
            if isinstance(parsed, dict) and isinstance(parsed.get("per_requirement"), dict):
                explanations = parsed["per_requirement"]
        except (ValueError, TypeError):
            pass
    result = []
    for requirement in application.job.jd_requirements:
        if profile is None:
            result.append(
                RequirementOut(
                    id=requirement.id,
                    text=requirement.text,
                    kind=requirement.kind,
                    status="not_evaluated",
                    explanation="Analysis has not completed.",
                    chunk_ids=[],
                )
            )
            continue
        match = matches.get(requirement.id, {})
        citations = list(
            dict.fromkeys(
                valid_ids[chunk_id]
                for chunk_id in match.get("resolved_chunk_ids", [])
                if chunk_id in valid_ids
            )
        )
        status = match.get("status", "missing")
        if status not in {"met", "partial", "missing"} or not citations:
            status = "missing"
        explanation = explanations.get(requirement.id, match.get("rationale", ""))
        result.append(
            RequirementOut(
                id=requirement.id,
                text=requirement.text,
                kind=requirement.kind,
                status=status,
                explanation=str(explanation)
                if citations
                else "No verified resume evidence available.",
                chunk_ids=citations,
            )
        )
    return sorted(result, key=lambda item: item.id)


def _row(application: Application) -> PipelineCandidate:
    profile = application.profile
    requirements = _requirements(application)
    must_have = [requirement for requirement in requirements if requirement.kind == "must_have"]
    return PipelineCandidate(
        id=application.id,
        job_id=application.job_id,
        name=application.name,
        status=application.status,
        vector_status=application.vector_status,
        created_at=application.created_at,
        score=profile.score if profile else None,
        recommendation=profile.recommendation if profile else None,
        confidence=profile.confidence if profile else None,
        must_have_met=sum(requirement.status == "met" for requirement in must_have),
        must_have_total=len(must_have),
        flags=list(profile.flags) if profile else [],
    )


def pipeline(
    db: Session,
    *,
    job_id: str | None = None,
    status: str | None = None,
    sort: str = "score_desc",
) -> list[PipelineCandidate]:
    statement = select(Application).options(
        selectinload(Application.profile),
        selectinload(Application.chunks),
        selectinload(Application.job).selectinload(Job.jd_requirements),
    )
    if job_id is not None:
        statement = statement.where(Application.job_id == job_id)
    if status is not None:
        statement = statement.where(Application.status == status)
    applications = list(db.scalars(statement).all())
    if sort == "created_desc":
        applications.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    else:
        applications.sort(
            key=lambda item: (
                item.profile is None,
                (-item.profile.score if sort == "score_desc" else item.profile.score)
                if item.profile
                else 0,
                item.id,
            )
        )
    return [_row(application) for application in applications]


def events(db: Session, application_id: str) -> list[EventOut]:
    _application(db, application_id)
    rows = db.scalars(
        select(Event)
        .where(Event.application_id == application_id)
        .order_by(Event.created_at, Event.id)
    ).all()
    return [EventOut.model_validate(event) for event in rows]


def detail(db: Session, application_id: str) -> CandidateDetail:
    application = _application(db, application_id)
    requirements = _requirements(application)
    skills = []
    if application.profile:
        for skill in application.profile.skills:
            extracted = skill.get("extracted", {})
            span = extracted.get("evidence_span", "")
            chunk_ids = [
                chunk.id for chunk in application.chunks if span.strip() and span in chunk.text
            ]
            if not chunk_ids:
                continue
            terms = (extracted.get("skill", ""), skill.get("canonical") or "")
            skills.append(
                SkillOut(
                    term=extracted.get("skill", ""),
                    canonical=skill.get("canonical") or "Unmapped",
                    chunk_ids=chunk_ids,
                    requirement_ids=[
                        requirement.id
                        for requirement in requirements
                        if set(chunk_ids).intersection(requirement.chunk_ids)
                        and any(
                            term.strip()
                            and re.search(
                                rf"(?<!\w){re.escape(term.strip())}(?!\w)",
                                requirement.text,
                                re.IGNORECASE,
                            )
                            for term in terms
                        )
                    ],
                )
            )
    return CandidateDetail(
        **_row(application).model_dump(),
        skills=skills,
        requirements=requirements,
        chunks=[
            ChunkOut.model_validate(chunk)
            for chunk in sorted(application.chunks, key=lambda chunk: (chunk.char_start, chunk.id))
        ],
        events=events(db, application_id),
    )


def _record_label(
    db: Session,
    application: Application,
    status: str,
    reason: str | None,
    *,
    action: str = "label_changed",
) -> None:
    old_status = application.status
    recommendation = application.profile.recommendation if application.profile else None
    expected = {"advance": "valid", "review": "pending", "decline": "rejected"}
    override = recommendation is not None and expected.get(recommendation) != status
    application.status = status
    db.add(
        Event(
            application_id=application.id,
            actor="hr",
            action=action,
            payload={
                "old_status": old_status,
                "status": status,
                "reason": reason,
                "recommendation": recommendation,
                "override": override,
            },
        )
    )
    if override:
        db.add(
            Event(
                application_id=application.id,
                actor="hr",
                action="recommendation_overridden",
                payload={"recommendation": recommendation, "status": status, "reason": reason},
            )
        )


def label(db: Session, application_id: str, body: StatusChange) -> PipelineCandidate:
    current = _application(db, application_id)
    _lock_job(db, current.job_id)
    application = _application(db, application_id, lock=True)
    if application.status not in {"analyzed", "pending", "valid", "rejected"}:
        raise HTTPException(status_code=409, detail="candidate is not ready for HR labelling")
    _record_label(db, application, body.status, body.reason)
    db.commit()
    return _row(application)


def _lock_job(db: Session, job_id: str) -> None:
    # Shared by previews/confirmations so competing pool promotions serialize.
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")


def promotion_preview(db: Session, job_id: str, percent: float) -> PromotionPreview:
    _lock_job(db, job_id)
    candidates = pipeline(db, job_id=job_id, status="pending")
    selected = candidates[: math.ceil(len(candidates) * percent / 100)]
    return PromotionPreview(
        job_id=job_id,
        percent=percent,
        pending_count=len(candidates),
        application_ids=[candidate.id for candidate in selected],
        candidates=selected,
    )


def promote(db: Session, job_id: str, body: PromotionConfirm) -> PromotionPreview:
    preview = promotion_preview(db, job_id, body.percent)
    if body.application_ids != preview.application_ids:
        raise HTTPException(status_code=409, detail="pending pool changed; preview again")
    # Lock every selected application and recheck; a manual label may have changed
    # while the pool was read. Never overwrite a concurrent human decision.
    selected = [
        _application(db, application_id, lock=True) for application_id in preview.application_ids
    ]
    if any(application.status != "pending" for application in selected):
        raise HTTPException(status_code=409, detail="pending pool changed; preview again")
    for application in selected:
        _record_label(
            db, application, "valid", f"Promote top {body.percent:g}%", action="pool_promoted"
        )
    db.commit()
    return preview.model_copy(
        update={"candidates": [_row(application) for application in selected]}
    )

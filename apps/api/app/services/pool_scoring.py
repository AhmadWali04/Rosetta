"""Recompute component-backed profiles atomically without changing HR decisions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Application, Event, Job, Profile
from app.graphs.state import ScoreComponents
from app.services.scoring import normalize_similarities, score_profile


def recompute_pool(db: Session, job_id: str, settings: Settings) -> None:
    """Caller commits scores and audit events with its intake transaction.

    All profile writes and HR status mutations take this job lock first. It
    serializes pool changes without allowing an intake to undo a human label.
    Profiles predating component persistence retain their existing scores.
    """
    with db.no_autoflush:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise ValueError(f"cannot rescore unknown job {job_id!r}")
    db.flush()
    profiles = list(
        db.scalars(
            select(Profile)
            .join(Application, Profile.application_id == Application.id)
            .where(Application.job_id == job_id)
            .order_by(Profile.application_id)
            .execution_options(populate_existing=True)
        ).all()
    )
    components = {
        profile.application_id: ScoreComponents.model_validate(profile.score_components)
        for profile in profiles
        if profile.score_components is not None
    }
    similarities = normalize_similarities(
        {identifier: value.semantic_similarity_raw for identifier, value in components.items()}
    )
    for profile in profiles:
        identifier = profile.application_id
        if identifier not in components:
            continue
        old = {
            "score": profile.score,
            "recommendation": profile.recommendation,
            "confidence": profile.confidence,
        }
        score, recommendation, confidence = score_profile(
            components[identifier], similarities[identifier], list(profile.flags), settings
        )
        updated = {"score": score, "recommendation": recommendation, "confidence": confidence}
        if old == updated:
            continue
        profile.score = score
        profile.recommendation = recommendation
        profile.confidence = confidence
        db.add(
            Event(
                application_id=identifier,
                actor="system",
                action="score_recomputed",
                payload={
                    "previous": old,
                    "current": updated,
                    "normalized_semantic_similarity": similarities[identifier],
                    "method": "job_pool_min_max_v1",
                },
            )
        )

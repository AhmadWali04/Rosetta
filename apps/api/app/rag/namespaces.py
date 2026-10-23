"""The ONLY place Pinecone namespace and record-ID strings are formatted.

See PRD §8.2. Every namespace is `{env}-...` where env is dev | demo | eval,
so eval runs never collide with demo data (AGENTS.md "Pinecone rules").
"""

from __future__ import annotations


def taxonomy_namespace(env: str) -> str:
    return f"{env}-taxonomy"


def jd_namespace(env: str, job_id: str) -> str:
    return f"{env}-jd-{job_id}"


def resumes_namespace(env: str, job_id: str) -> str:
    return f"{env}-resumes-{job_id}"


def candidates_namespace(env: str, job_id: str) -> str:
    return f"{env}-candidates-{job_id}"


def skill_record_id(taxonomy_id: str) -> str:
    return f"skill#{taxonomy_id}"


def requirement_record_id(requirement_id: str) -> str:
    return f"req#{requirement_id}"


def chunk_record_id(application_id: str, chunk_idx: int) -> str:
    return f"{application_id}#chunk#{chunk_idx}"


def candidate_summary_record_id(application_id: str) -> str:
    return f"{application_id}#summary"


def application_id_prefix(application_id: str) -> str:
    """Prefix used by delete-by-prefix to purge every record for an application
    (PRD §8.7 / AGENTS.md invariant 9)."""
    return f"{application_id}#"

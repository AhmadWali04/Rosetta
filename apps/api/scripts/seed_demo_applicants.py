"""Demo-ready applicant pool for the HR/Copilot/Tech-Lead portals.

Under a hard demo deadline, this directly constructs `Application` +
`ResumeChunk` + `Profile` + `Event` rows with hand-authored, realistic data
spanning every PRD §10 tier (strong, strong-but-different-vocabulary,
keyword-stuffed, injection-flagged), rather than running the real intake
graph end-to-end (which needs live OpenAI calls the account currently has
no credits for). Every citation/skill reference below points at a chunk
actually created in this same run, matching `app/services/hr.py`'s exact
expectations (`skills` require the evidence_span substring to literally
appear in a chunk's text; `requirement_matches` reference real chunk ids).

Idempotent: deletes any previously-seeded demo applicants (ids prefixed
`demo-`) before inserting. Run with:
    cd apps/api && uv run --env-file ../../.env python -m scripts.seed_demo_applicants
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete

from app.db.models import Application, Event, Profile, ResumeChunk
from app.db.session import SessionLocal
from app.rag import namespaces

JOB_ID = "job-ai-intern-procogia"
REQ = {
    "edu": "job-ai-intern-procogia-req-00",
    "python": "job-ai-intern-procogia-req-01",
    "fullstack": "job-ai-intern-procogia-req-02",
    "react": "job-ai-intern-procogia-req-03",
    "genai": "job-ai-intern-procogia-req-04",
    "problem_solving": "job-ai-intern-procogia-req-05",
    "agents": "job-ai-intern-procogia-req-06",
    "rag": "job-ai-intern-procogia-req-07",
    "cloud": "job-ai-intern-procogia-req-08",
    "oss": "job-ai-intern-procogia-req-09",
}


def _chunk(app_id: str, idx: int, section: str, text: str) -> ResumeChunk:
    return ResumeChunk(
        id=f"{app_id}#chunk#{idx}",
        application_id=app_id,
        chunk_idx=idx,
        section=section,
        text=text,
        char_start=0,
        char_end=len(text),
        pinecone_id=namespaces.chunk_record_id(app_id, idx),
        embed_model="demo-seed",
        indexed_at=datetime.utcnow(),
    )


def _skill(term: str, canonical: str, taxonomy_id: str, span: str, depth: str) -> dict:
    return {
        "extracted": {
            "skill": term,
            "evidence_span": span,
            "context": span,
            "recency": "current",
            "depth_signal": depth,
        },
        "canonical": canonical,
        "taxonomy_id": taxonomy_id,
    }


def _match(req_id: str, status: str, chunk_ids: list[str], rationale: str) -> dict:
    return {
        "requirement_id": req_id,
        "status": status,
        "cited_chunk_ids": chunk_ids,
        "resolved_chunk_ids": chunk_ids,
        "rationale": rationale,
    }


def _explanation(per_requirement: dict[str, str], overall: str) -> str:
    return json.dumps({"per_requirement": per_requirement, "overall": overall})


def _copy_fixture(app_id: str, fixture_name: str) -> str:
    """Writes the file to the repo-root `data/uploads/` (the directory the
    Docker containers actually have volume-mounted at `/app/data/uploads`),
    regardless of this script's own cwd, and returns the DB-stored
    `resume_path` string in the same Docker-cwd-relative form
    `app/services/applications.py` already uses (`data/uploads/<id>/<file>`)
    — NOT `settings.resume_upload_dir` resolved against *this* process's
    cwd, which would be wrong when this script is run from `apps/api/`
    (see the M1 PROGRESS.md note on this being a cwd-dependent rough edge).
    """
    repo_root = Path(__file__).resolve().parents[3]
    src = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "resumes" / fixture_name
    dest_dir = repo_root / "data" / "uploads" / app_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest_dir / fixture_name)
    return f"data/uploads/{app_id}/{fixture_name}"


def _applicant(**kwargs) -> dict:
    return kwargs


APPLICANTS = [
    _applicant(
        id="demo-strong-01",
        name="Avery Chen",
        email="avery.chen@example.com",
        fixture="strong.txt",
        recommendation="advance",
        score=0.86,
        confidence=0.82,
        flags=[],
        chunks=[
            (
                "experience",
                "Built and deployed a production RAG pipeline in Python using LangChain and "
                "Pinecone, serving 10k+ queries/day with citation-grounded answers.",
            ),
            (
                "experience",
                "Shipped a full-stack internal tool: React frontend, FastAPI backend, "
                "PostgreSQL, deployed on AWS with CI/CD via GitHub Actions.",
            ),
            (
                "projects",
                "Designed a multi-agent LangGraph workflow that routes customer support "
                "tickets, with human-in-the-loop approval before any status change.",
            ),
            (
                "education",
                "Final-year Computer Science student, expected graduation April 2027.",
            ),
        ],
        skills=[
            (
                "RAG pipelines",
                "Retrieval-Augmented Generation",
                "skill-rag",
                "production RAG pipeline in Python using LangChain and Pinecone",
                "production",
                0,
            ),
            ("React", "React", "skill-react", "React frontend, FastAPI backend", "production", 1),
            (
                "LangGraph",
                "LangGraph",
                "skill-langgraph",
                "multi-agent LangGraph workflow",
                "production",
                2,
            ),
        ],
        matches=[
            (
                REQ["python"],
                "met",
                [0, 1],
                "Built a production Python RAG pipeline and a FastAPI backend.",
            ),
            (
                REQ["fullstack"],
                "met",
                [1],
                "Shipped a full-stack tool: React + FastAPI + Postgres.",
            ),
            (REQ["react"], "met", [1], "React frontend explicitly named."),
            (
                REQ["genai"],
                "met",
                [0, 2],
                "Hands-on production RAG and multi-agent LangGraph work.",
            ),
            (
                REQ["agents"],
                "met",
                [2],
                "Built a multi-agent LangGraph workflow with HITL approval.",
            ),
            (REQ["rag"], "met", [0], "Production RAG pipeline with citation-grounded answers."),
            (REQ["edu"], "met", [3], "Final-year CS student, graduating April 2027."),
            (
                REQ["problem_solving"],
                "partial",
                [2],
                "Evidence of independent system design, less on debugging specifics.",
            ),
        ],
        overall=(
            "Strong match: hands-on production experience with RAG, agents, "
            "and full-stack delivery."
        ),
    ),
    _applicant(
        id="demo-vocab-02",
        name="Priya Natarajan",
        email="priya.n@example.com",
        fixture="different_vocabulary_strong.txt",
        recommendation="advance",
        score=0.74,
        confidence=0.68,
        flags=[],
        chunks=[
            (
                "experience",
                "Automated data pipelines using Python and cloud functions, reducing manual "
                "ETL work by 70% across three internal reporting systems.",
            ),
            (
                "experience",
                "Integrated a large language model into a document Q&A tool for the support "
                "team, with source linking back to the original paragraph.",
            ),
            (
                "projects",
                "Built backend services and a lightweight web dashboard that talk to each "
                "other over a REST API, deployed on Google Cloud.",
            ),
        ],
        skills=[
            (
                "cloud automation",
                "Cloud Functions",
                "skill-cloud",
                "Python and cloud functions",
                "production",
                0,
            ),
            (
                "document Q&A with LLMs",
                "Retrieval-Augmented Generation",
                "skill-rag",
                "large language model into a document Q&A tool",
                "project",
                1,
            ),
        ],
        matches=[
            (REQ["python"], "met", [0], "Automated data pipelines using Python."),
            (
                REQ["fullstack"],
                "met",
                [2],
                "Backend services talking to a web dashboard over REST.",
            ),
            (
                REQ["genai"],
                "partial",
                [1],
                "LLM integration into a Q&A tool, different vocabulary than "
                "'agentic AI' but same substance.",
            ),
            (
                REQ["rag"],
                "partial",
                [1],
                "Source-linking Q&A tool is functionally RAG, described differently.",
            ),
            (REQ["cloud"], "met", [0, 2], "Cloud functions and Google Cloud deployment."),
            (REQ["edu"], "missing", [], "No education section found in this resume excerpt."),
        ],
        overall=(
            "Real hands-on AI/cloud experience described in different vocabulary than "
            "the JD — not a keyword match, but the substance is there."
        ),
    ),
    _applicant(
        id="demo-review-03",
        name="Jordan Kim",
        email="jordan.kim@example.com",
        fixture="sample.docx",
        recommendation="review",
        score=0.52,
        confidence=0.55,
        flags=[],
        chunks=[
            (
                "experience",
                "Completed coursework projects using Python for data analysis and basic "
                "scripting during a summer research position.",
            ),
            (
                "skills",
                "Familiar with React basics and built a small personal portfolio site.",
            ),
        ],
        skills=[
            ("Python", "Python", "skill-python", "Python for data analysis", "coursework", 0),
            ("React", "React", "skill-react", "React basics", "coursework", 1),
        ],
        matches=[
            (REQ["python"], "partial", [0], "Coursework-level Python, not production use."),
            (REQ["react"], "partial", [1], "Basic React familiarity, personal project only."),
            (REQ["genai"], "missing", [], "No AI/LLM experience evidenced in the resume."),
            (REQ["edu"], "met", [0], "Summer research position implies current enrollment."),
        ],
        overall=(
            "Promising fundamentals but limited depth on AI/agentic requirements — "
            "worth a closer look."
        ),
    ),
    _applicant(
        id="demo-stuffed-04",
        name="Taylor Brooks",
        email="taylor.brooks@example.com",
        fixture="keyword_stuffed.txt",
        recommendation="decline",
        score=0.31,
        confidence=0.4,
        flags=["keyword_stuffing_suspected"],
        chunks=[
            (
                "skills",
                "Skills: Python, React, Node.js, AWS, GCP, Azure, LangChain, LangGraph, RAG, "
                "agentic AI, Kubernetes, Docker, FastAPI, PostgreSQL, Pinecone, Kafka.",
            ),
        ],
        skills=[
            ("Python", "Python", "skill-python", "Python, React", "list_only", 0),
            ("LangChain", "LangChain", "skill-langchain", "LangChain, LangGraph", "list_only", 0),
        ],
        matches=[
            (
                REQ["python"],
                "partial",
                [0],
                "Listed only, no project or production evidence found.",
            ),
            (REQ["genai"], "partial", [0], "Listed only, no demonstrated depth."),
            (REQ["agents"], "missing", [], "No evidence beyond a bare keyword list."),
        ],
        overall=(
            "Every JD keyword appears in a flat list with no supporting project "
            "evidence — likely keyword stuffing."
        ),
    ),
    _applicant(
        id="demo-injection-05",
        name="Morgan Lee",
        email="morgan.lee@example.com",
        fixture="injection_attempt.txt",
        recommendation="review",
        score=0.4,
        confidence=0.3,
        flags=["prompt_injection_suspected"],
        chunks=[
            (
                "experience",
                "Built a few small Python scripts for personal projects, "
                "limited professional experience.",
            ),
        ],
        skills=[
            ("Python", "Python", "skill-python", "small Python scripts", "project", 0),
        ],
        matches=[
            (REQ["python"], "partial", [0], "Some personal-project Python experience."),
            (REQ["genai"], "missing", [], "No AI/agentic experience evidenced."),
        ],
        overall=(
            "Resume contained text attempting to instruct the AI reviewer directly — "
            "flagged for human review, score unaffected by the injection attempt itself."
        ),
    ),
]


def main() -> None:
    ids = [a["id"] for a in APPLICANTS]

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.application_id.in_(ids)))
        session.execute(delete(ResumeChunk).where(ResumeChunk.application_id.in_(ids)))
        session.execute(delete(Profile).where(Profile.application_id.in_(ids)))
        session.execute(delete(Application).where(Application.id.in_(ids)))
        session.commit()

        now = datetime.utcnow()
        for i, a in enumerate(APPLICANTS):
            resume_path = _copy_fixture(a["id"], a["fixture"])
            created_at = now - timedelta(hours=len(APPLICANTS) - i)

            application = Application(
                id=a["id"],
                job_id=JOB_ID,
                name=a["name"],
                email=a["email"],
                links={},
                resume_path=resume_path,
                status="analyzed",
                vector_status="indexed",
                created_at=created_at,
            )
            session.add(application)

            chunk_rows = [
                _chunk(a["id"], idx, section, text)
                for idx, (section, text) in enumerate(a["chunks"])
            ]
            for row in chunk_rows:
                session.add(row)

            skills = [
                _skill(term, canonical, tax_id, span, depth)
                for term, canonical, tax_id, span, depth in [
                    (s[0], s[1], s[2], s[3], s[4]) for s in a["skills"]
                ]
            ]
            requirement_matches = [
                _match(
                    req_id,
                    status,
                    [chunk_rows[idx].id for idx in chunk_idxs],
                    rationale,
                )
                for req_id, status, chunk_idxs, rationale in a["matches"]
            ]
            per_requirement = {m["requirement_id"]: m["rationale"] for m in requirement_matches}

            session.add(
                Profile(
                    application_id=a["id"],
                    skills=skills,
                    requirement_matches=requirement_matches,
                    score=a["score"],
                    recommendation=a["recommendation"],
                    confidence=a["confidence"],
                    score_components=None,
                    flags=a["flags"],
                    explanation=_explanation(per_requirement, a["overall"]),
                )
            )

            session.add(
                Event(
                    application_id=a["id"],
                    actor="applicant",
                    action="application_submitted",
                    payload={"job_id": JOB_ID, "name": a["name"], "email": a["email"]},
                    created_at=created_at,
                )
            )
            session.add(
                Event(
                    application_id=a["id"],
                    actor="system",
                    action="intake_complete",
                    payload={"recommendation": a["recommendation"], "score": a["score"]},
                    created_at=created_at + timedelta(seconds=30),
                )
            )

        session.commit()

    print(f"[seed_demo_applicants] seeded {len(APPLICANTS)} demo applicants for job '{JOB_ID}'")


if __name__ == "__main__":
    main()

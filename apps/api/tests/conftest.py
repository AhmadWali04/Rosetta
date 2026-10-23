"""Shared pytest fixtures.

AGENTS.md "Testing rules": unit tests never touch a live DB/network. An
in-memory sqlite engine stands in for Postgres here so route/service tests
don't need a running `db` container (this project only uses
Postgres-portable SQLAlchemy features in app/db/models.py — JSON, String,
Float, etc. — so sqlite is a safe stand-in for this layer's tests).

Also puts apps/worker on sys.path so tests/test_worker.py can `import
runner` the exact way the worker container does it (its script's own
directory is sys.path[0] there — see apps/worker/main.py).
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base, Job
from app.db.session import get_session
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_DIR = REPO_ROOT / "apps" / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

SEED_JOB_ID = "job-ai-intern-procogia"


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    session = testing_session_local()
    session.add(Job(id=SEED_JOB_ID, title="AI Intern", raw_jd="raw jd text", requirements=[]))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def settings_with_tmp_dir(tmp_path, monkeypatch):
    """Points `resume_upload_dir` at a pytest tmp dir instead of the real
    (relative, cwd-dependent) `data/uploads` default, so tests never write
    into the repo. Monkeypatches the `get_settings` name as imported into
    app.services.applications specifically, since that's where
    `create_application` calls it."""
    settings = get_settings().model_copy(update={"resume_upload_dir": str(tmp_path)})
    monkeypatch.setattr("app.services.applications.get_settings", lambda: settings)
    return settings

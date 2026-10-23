"""HTTP-layer tests for /jobs."""

from __future__ import annotations

SEED_JOB_ID = "job-ai-intern-procogia"


def test_get_job_route_returns_seeded_job(client):
    response = client.get(f"/jobs/{SEED_JOB_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == SEED_JOB_ID


def test_get_job_route_not_found(client):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404

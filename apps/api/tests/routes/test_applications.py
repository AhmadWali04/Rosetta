"""HTTP-layer tests for /applications, using FastAPI's TestClient against
app.main.app with the DB session dependency overridden to an in-memory
sqlite (see tests/conftest.py)."""

from __future__ import annotations

import io

SEED_JOB_ID = "job-ai-intern-procogia"


def _multipart_payload(**overrides: str) -> dict[str, str]:
    data = {
        "job_id": SEED_JOB_ID,
        "name": "Jordan Applicant",
        "email": "jordan@example.com",
    }
    data.update(overrides)
    return data


def test_submit_application_success(client, settings_with_tmp_dir):
    files = {"resume": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    response = client.post("/applications", data=_multipart_payload(), files=files)

    assert response.status_code == 201
    body = response.json()
    assert body["job_id"] == SEED_JOB_ID
    assert body["status"] == "submitted"
    assert body["vector_status"] == "pending"


def test_submit_application_rejects_bad_content_type(client, settings_with_tmp_dir):
    files = {"resume": ("resume.txt", io.BytesIO(b"plain text"), "text/plain")}
    response = client.post("/applications", data=_multipart_payload(), files=files)
    assert response.status_code == 422


def test_submit_application_rejects_oversized_file(client, settings_with_tmp_dir):
    settings_with_tmp_dir.resume_upload_max_mb = 0.001
    files = {"resume": ("resume.pdf", io.BytesIO(b"x" * 4096), "application/pdf")}
    response = client.post("/applications", data=_multipart_payload(), files=files)
    assert response.status_code == 422


def test_submit_application_unknown_job_returns_404(client, settings_with_tmp_dir):
    files = {"resume": ("resume.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    response = client.post(
        "/applications", data=_multipart_payload(job_id="does-not-exist"), files=files
    )
    assert response.status_code == 404


def test_get_application_not_found(client):
    response = client.get("/applications/does-not-exist")
    assert response.status_code == 404


def test_list_applications_empty(client):
    response = client.get("/applications")
    assert response.status_code == 200
    assert response.json() == []

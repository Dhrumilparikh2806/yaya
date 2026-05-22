"""
Unit tests for POST /v1/query, GET /v1/documents, GET /v1/documents/{id}/summary,
and admin endpoints.  No real Gemini/ChromaDB calls — all patched.
"""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.db import Job, JobStatus, User, UserRole
from app.security import hash_password


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register_login(client, email, password="pass123", role="user"):
    client.post("/auth/register", json={"email": email, "password": password, "role": role})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_completed_job(db: Session, user_id) -> Job:
    job = Job(
        user_id=user_id,
        filename="test.pdf",
        file_type="pdf",
        file_path="/tmp/test.pdf",
        file_size_bytes=1000,
        status=JobStatus.completed,
        step="completed",
        chunk_count=5,
        result=json.dumps({"title": "Test Doc", "summary": "A summary."}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ── Query endpoint ─────────────────────────────────────────────────────────────

def test_query_requires_auth(client: TestClient):
    resp = client.post("/v1/query", json={"question": "hello"})
    assert resp.status_code == 401


def test_query_empty_question_422(client: TestClient):
    token = _register_login(client, "quser422@example.com")
    resp = client.post("/v1/query", json={"question": ""}, headers=_auth(token))
    assert resp.status_code == 422


def test_query_no_completed_jobs_400(client: TestClient):
    token = _register_login(client, "quser_nojobs@example.com")
    resp = client.post("/v1/query", json={"question": "What is AI?"}, headers=_auth(token))
    assert resp.status_code == 400
    assert "No processed documents" in resp.json()["detail"]


def test_query_returns_answer(client: TestClient, db: Session):
    token = _register_login(client, "quser_ans@example.com")
    # Get user from DB
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "quser_ans@example.com")).first()
    _create_completed_job(db, user.id)

    fake_result = {
        "answer": "Machine learning is awesome [1].",
        "citations": [{"index": 1, "filename": "test.pdf", "page_or_segment": "page 1", "excerpt": "ML text"}],
        "confidence_gate_passed": True,
        "avg_similarity_score": 0.82,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "latency_ms": 500,
        "ragas_scores": None,
    }
    with patch("app.rag.engine.query", return_value=fake_result):
        resp = client.post("/v1/query", json={"question": "What is ML?"}, headers=_auth(token))

    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence_gate_passed"] is True
    assert "citations" in data
    assert data["prompt_tokens"] == 100


def test_query_specific_job_ids(client: TestClient, db: Session):
    token = _register_login(client, "quser_jids@example.com")
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "quser_jids@example.com")).first()
    job = _create_completed_job(db, user.id)

    fake_result = {
        "answer": "Answer [1].",
        "citations": [],
        "confidence_gate_passed": True,
        "avg_similarity_score": 0.9,
        "prompt_tokens": 50,
        "completion_tokens": 20,
        "latency_ms": 300,
        "ragas_scores": None,
    }
    with patch("app.rag.engine.query", return_value=fake_result):
        resp = client.post(
            "/v1/query",
            json={"question": "Explain?", "job_ids": [str(job.id)]},
            headers=_auth(token),
        )
    assert resp.status_code == 200


def test_query_wrong_job_id_403(client: TestClient, db: Session):
    token_a = _register_login(client, "quser_a@example.com")
    token_b = _register_login(client, "quser_b@example.com")
    from sqlmodel import select
    user_a = db.exec(select(User).where(User.email == "quser_a@example.com")).first()
    job = _create_completed_job(db, user_a.id)

    resp = client.post(
        "/v1/query",
        json={"question": "What?", "job_ids": [str(job.id)]},
        headers=_auth(token_b),
    )
    assert resp.status_code == 403


# ── Documents endpoint ─────────────────────────────────────────────────────────

def test_list_documents_empty(client: TestClient):
    token = _register_login(client, "docuser_empty@example.com")
    resp = client.get("/v1/documents", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_documents_returns_completed(client: TestClient, db: Session):
    token = _register_login(client, "docuser_comp@example.com")
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "docuser_comp@example.com")).first()
    _create_completed_job(db, user.id)

    resp = client.get("/v1/documents", headers=_auth(token))
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) >= 1
    assert docs[0]["filename"] == "test.pdf"
    assert docs[0]["status"] == "COMPLETED"


def test_document_summary(client: TestClient, db: Session):
    token = _register_login(client, "docuser_sum@example.com")
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "docuser_sum@example.com")).first()
    job = _create_completed_job(db, user.id)

    resp = client.get(f"/v1/documents/{job.id}/summary", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == str(job.id)
    assert "summary" in data
    assert data["summary"]["title"] == "Test Doc"


def test_document_summary_not_completed(client: TestClient, db: Session):
    token = _register_login(client, "docuser_pend@example.com")
    from sqlmodel import select
    user = db.exec(select(User).where(User.email == "docuser_pend@example.com")).first()
    job = Job(
        user_id=user.id, filename="pending.pdf", file_type="pdf",
        file_path="/tmp/x.pdf", file_size_bytes=100,
        status=JobStatus.processing, step="extracting",
    )
    db.add(job); db.commit(); db.refresh(job)

    resp = client.get(f"/v1/documents/{job.id}/summary", headers=_auth(token))
    assert resp.status_code == 400


# ── Admin endpoints ────────────────────────────────────────────────────────────

def test_admin_endpoints_require_admin(client: TestClient):
    token = _register_login(client, "nonadmin6@example.com")
    for path in ["/v1/admin/usage", "/v1/admin/ragas", "/v1/admin/users", "/v1/admin/logs"]:
        resp = client.get(path, headers=_auth(token))
        assert resp.status_code == 403, f"{path} should return 403"


def test_admin_usage_returns_data(client: TestClient):
    token = _register_login(client, "admin6@example.com", role="admin")
    resp = client.get("/v1/admin/usage", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tokens" in data
    assert "by_day" in data
    assert "by_endpoint" in data


def test_admin_users_returns_list(client: TestClient):
    token = _register_login(client, "admin6b@example.com", role="admin")
    resp = client.get("/v1/admin/users", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


def test_admin_logs_returns_list(client: TestClient):
    token = _register_login(client, "admin6c@example.com", role="admin")
    resp = client.get("/v1/admin/logs", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_admin_patch_user(client: TestClient, db: Session):
    admin_token = _register_login(client, "admin6d@example.com", role="admin")
    _register_login(client, "target6@example.com")
    from sqlmodel import select
    target = db.exec(select(User).where(User.email == "target6@example.com")).first()

    resp = client.patch(
        f"/v1/admin/users/{target.id}",
        json={"is_active": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_admin_cannot_deactivate_self(client: TestClient, db: Session):
    admin_token = _register_login(client, "admin6e@example.com", role="admin")
    from sqlmodel import select
    admin = db.exec(select(User).where(User.email == "admin6e@example.com")).first()

    resp = client.patch(
        f"/v1/admin/users/{admin.id}",
        json={"is_active": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400

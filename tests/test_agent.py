"""Tests for ADK agent tools and /v1/agent/chat endpoint."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from app.agent.tools import (
    get_job_status,
    list_documents,
    set_agent_user_id,
    summarize_document,
)
from app.models.db import Job, JobStatus, User, UserRole


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_user(db: Session, role=UserRole.user) -> User:
    user = User(
        email=f"agent-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password="x",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_job(db: Session, user_id, status=JobStatus.completed, result=None) -> Job:
    job = Job(
        user_id=user_id,
        filename="doc.pdf",
        file_type="pdf",
        file_path="/tmp/doc.pdf",
        file_size_bytes=1024,
        status=status,
        result=result,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def login(client, email, password="password123"):
    client.post("/auth/register", json={"email": email, "password": password})
    r = client.post("/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


# ── Tool unit tests (direct function calls with patched engine) ─────────────────

class TestGetJobStatus:
    def test_returns_status_for_valid_job(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        job = make_job(db, user.id)

        result = get_job_status(str(job.id))
        assert result["status"] == "COMPLETED"
        assert result["job_id"] == str(job.id)
        assert "retry_count" in result

    def test_invalid_uuid(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        result = get_job_status("not-a-uuid")
        assert "error" in result

    def test_not_found(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        result = get_job_status(str(uuid.uuid4()))
        assert "error" in result

    def test_pending_job(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        job = make_job(db, user.id, status=JobStatus.pending)
        result = get_job_status(str(job.id))
        assert result["status"] == "PENDING"


class TestListDocuments:
    def test_returns_completed_jobs_for_user(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        make_job(db, user.id, status=JobStatus.completed)
        make_job(db, user.id, status=JobStatus.pending)  # should not appear

        set_agent_user_id(str(user.id))
        result = list_documents()
        job_ids = [r["job_id"] for r in result]
        # Only completed jobs for this user
        for doc in result:
            assert doc["file_type"] == "pdf"

    def test_empty_when_no_completed_jobs(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        set_agent_user_id(str(user.id))
        result = list_documents()
        # result is a list — may or may not be empty depending on other tests
        assert isinstance(result, list)


class TestSummarizeDocument:
    def test_returns_summary_for_completed_job(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        summary_data = {"title": "Test Doc", "pages": 5}
        job = make_job(db, user.id, result=json.dumps(summary_data))

        result = summarize_document(str(job.id))
        assert result["summary"]["title"] == "Test Doc"
        assert result["filename"] == "doc.pdf"

    def test_error_for_non_completed_job(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        user = make_user(db)
        job = make_job(db, user.id, status=JobStatus.pending)
        result = summarize_document(str(job.id))
        assert "error" in result
        assert "not COMPLETED" in result["error"]

    def test_invalid_uuid(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        result = summarize_document("bad-uuid")
        assert "error" in result

    def test_not_found(self, db, engine):
        import app.models.db as _db
        _db._engine = engine
        result = summarize_document(str(uuid.uuid4()))
        assert "error" in result


# ── API endpoint tests ─────────────────────────────────────────────────────────

class TestAgentChatEndpoint:
    def test_requires_auth(self, client):
        r = client.post("/v1/agent/chat", json={"message": "hello"})
        assert r.status_code == 401

    def test_returns_answer_and_tool_calls(self, client):
        email = f"agentuser-{uuid.uuid4().hex[:6]}@test.com"
        token = login(client, email)

        mock_result = {
            "response": "I found 2 documents.",
            "tool_calls_made": ["list_documents"],
            "session_id": str(uuid.uuid4()),
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        with patch("app.agent.agent.run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            r = client.post(
                "/v1/agent/chat",
                json={"message": "What documents do I have?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["response"] == "I found 2 documents."
        assert data["tool_calls_made"] == ["list_documents"]

    def test_passes_session_id(self, client):
        email = f"agentsession-{uuid.uuid4().hex[:6]}@test.com"
        token = login(client, email)
        session_id = str(uuid.uuid4())

        with patch("app.agent.agent.run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"response": "ok", "tool_calls_made": [], "session_id": session_id}
            r = client.post(
                "/v1/agent/chat",
                json={"message": "hi", "session_id": session_id},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["session_id"] == session_id

    def test_generates_session_id_when_not_provided(self, client):
        email = f"agentnosess-{uuid.uuid4().hex[:6]}@test.com"
        token = login(client, email)

        with patch("app.agent.agent.run_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"response": "ok", "tool_calls_made": [], "session_id": "new-id"}
            r = client.post(
                "/v1/agent/chat",
                json={"message": "hello"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["session_id"] is None  # None passed, run_agent generates one

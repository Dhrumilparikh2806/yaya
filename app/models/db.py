import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session
from sqlalchemy import text


# ── Enums ──────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class JobStatus(str, enum.Enum):
    pending = "PENDING"
    processing = "PROCESSING"
    completed = "COMPLETED"
    failed = "FAILED"
    failed_permanent = "FAILED_PERMANENT"


class ErrorType(str, enum.Enum):
    rate_limit = "RATE_LIMIT"
    invalid_input = "INVALID_INPUT"
    unknown = "UNKNOWN"


# ── Tables ─────────────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.user)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: Optional[datetime] = Field(default=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    filename: str
    file_type: str
    file_path: str
    file_size_bytes: int
    status: JobStatus = Field(default=JobStatus.pending)
    step: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    error_type: Optional[ErrorType] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    result: Optional[str] = Field(default=None)
    chunk_count: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UsageLog(SQLModel, table=True):
    __tablename__ = "usage_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    job_id: Optional[uuid.UUID] = Field(default=None, foreign_key="jobs.id", index=True)
    endpoint: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    query_text: Optional[str] = Field(default=None)
    llm_response_preview: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QueryHistory(SQLModel, table=True):
    __tablename__ = "query_history"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    question: str
    answer: str
    citations: str
    job_ids_queried: str
    chunk_count_retrieved: int
    avg_similarity_score: float
    confidence_gate_passed: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    ragas_scores: Optional[str] = Field(default=None)
    ragas_computed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Engine helpers ─────────────────────────────────────────────────────────────

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from app.config import settings
        _engine = create_engine(settings.DATABASE_URL, echo=False)
    return _engine


def create_db_and_tables():
    SQLModel.metadata.create_all(get_engine())

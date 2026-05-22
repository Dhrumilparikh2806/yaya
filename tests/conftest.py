import os
import pytest
from sqlmodel import SQLModel, Session, create_engine
from fastapi.testclient import TestClient

# Use SQLite in-memory DB for tests — never touches PostgreSQL
TEST_DATABASE_URL = "sqlite:///./test_geminirag.db"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GEMINI_API_KEY", "test_key_placeholder_for_tests")
os.environ.setdefault("SECRET_KEY", "test_secret_key_minimum_32_chars_here!!")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8001")


@pytest.fixture(scope="session")
def engine():
    from app.models.db import get_engine
    eng = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c

"""
Pydantic-settings configuration loaded from the .env file.

P0 variables (GROQ_API_KEY, SECRET_KEY, DATABASE_URL, REDIS_URL) are validated
in model_post_init and cause an immediate sys.exit(1) if missing or still set to
placeholder values, so misconfiguration is caught at startup rather than at
the first API call.

GEMINI_API_KEY is optional and only required for the /v1/query/stream SSE
endpoint.  All other LLM work uses Groq.
"""

import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_VALUES = {
    "your_gemini_api_key_here",
    "your_groq_api_key_here",
    "change_me_to_a_long_random_string",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # P0 — required
    GROQ_API_KEY: str
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str

    # Gemini kept only for ADK agent (not used in pipeline)
    GEMINI_API_KEY: str = ""

    # P1 — defaults provided
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION: str = "geminirag_chunks"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    UPLOAD_DIR: str = "/tmp/geminirag_uploads"

    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_PROCESSING_MODEL: str = "llama-3.1-8b-instant"
    GROQ_VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # Kept for ADK agent and backward compat
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"

    WHISPER_MODEL: str = "whisper-large-v3"
    WHISPER_LANGUAGE: str = ""   # empty = auto-detect; set to ISO-639-1 code ("en","hi","es"…) to force
    VIDEO_FRAME_INTERVAL: int = 60
    DIARIZATION_THRESHOLD: float = 0.4
    MAX_AUDIO_CHUNK_MB: int = 20

    CHUNK_SIZE: int = 600
    CHILD_CHUNK_SIZE: int = 150
    CHUNK_OVERLAP: int = 50
    RAG_TOP_K: int = 8
    CONFIDENCE_THRESHOLD: float = 0.4

    CELERY_MAX_RETRIES: int = 3
    CELERY_RETRY_BACKOFF: int = 60

    OTEL_EXPORTER: str = "stdout"
    OTEL_SERVICE_NAME: str = "geminirag"

    ALLOWED_ORIGINS: str = "http://localhost:5173"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    def model_post_init(self, __context) -> None:
        errors = []
        if not self.GROQ_API_KEY or self.GROQ_API_KEY in _PLACEHOLDER_VALUES:
            errors.append("GROQ_API_KEY is missing or still a placeholder")
        if not self.SECRET_KEY or self.SECRET_KEY in _PLACEHOLDER_VALUES:
            errors.append("SECRET_KEY is missing or still a placeholder")
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL is missing")
        if errors:
            import sys as _sys
            _sys.stderr.write("STARTUP ERROR — missing required environment variables:\n")
            for e in errors:
                _sys.stderr.write(f"  • {e}\n")
            _sys.exit(1)


settings = Settings()


def get_settings() -> Settings:
    return settings

import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_VALUES = {
    "your_gemini_api_key_here",
    "change_me_to_a_long_random_string",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # P0 — required
    GEMINI_API_KEY: str
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str

    # P1 — defaults provided
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION: str = "geminirag_chunks"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    UPLOAD_DIR: str = "/tmp/geminirag_uploads"

    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"

    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 5
    CONFIDENCE_THRESHOLD: float = 0.65

    CELERY_MAX_RETRIES: int = 3
    CELERY_RETRY_BACKOFF: int = 60

    OTEL_EXPORTER: str = "stdout"
    OTEL_SERVICE_NAME: str = "geminirag"

    def model_post_init(self, __context) -> None:
        errors = []
        if not self.GEMINI_API_KEY or self.GEMINI_API_KEY in _PLACEHOLDER_VALUES:
            errors.append("GEMINI_API_KEY is missing or still a placeholder")
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

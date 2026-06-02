"""
FastAPI application factory.

Responsibilities:
- Configures structlog and OpenTelemetry on startup.
- Registers CORS, slowapi rate-limiting, and per-request JSON logging middleware.
- Warms up fastembed (ONNX Runtime) synchronously in the main thread at startup
  to avoid a crash on Python 3.13+ when it first loads inside a thread-pool worker.
- Mounts all API routers under /auth and /v1.
- Exposes a /health endpoint that probes PostgreSQL and ChromaDB.
"""

import os
import time
import uuid as _uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import configure_tracing
from app.api import auth, files, jobs, query, documents, admin, agent


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="GeminiRAG", version="1.0.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    configure_tracing(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = str(_uuid.uuid4())
        start = time.time()
        response = await call_next(request)
        latency_ms = int((time.time() - start) * 1000)

        user_id = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.security import decode_token
                payload = decode_token(auth_header.split(" ", 1)[1])
                user_id = payload.get("sub")
            except Exception:
                pass

        get_logger().info(
            "http_request",
            request_id=request_id,
            user_id=user_id,
            endpoint=str(request.url.path),
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        return response

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(files.router, prefix="/v1", tags=["files"])
    app.include_router(jobs.router, prefix="/v1", tags=["jobs"])
    app.include_router(query.router, prefix="/v1", tags=["query"])
    app.include_router(documents.router, prefix="/v1", tags=["documents"])
    app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])
    app.include_router(agent.router, prefix="/v1", tags=["agent"])

    @app.on_event("startup")
    def warmup_models():
        """Warm up native-code models at startup.

        fastembed (ONNX Runtime) is loaded synchronously in the main thread —
        it must be initialised here because ONNX Runtime crashes when first called
        from a uvicorn thread-pool worker on Python 3.13+.

        The sentence-transformers CrossEncoder (reranker) is loaded asynchronously
        in a daemon background thread because its Rust tokenizer deadlocks when
        stdout is not a TTY. It sets a threading.Event when ready; queries wait up
        to 60 s for it, then fall back to returning un-reranked top-k results.
        """
        from app.config import settings as _s
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["TQDM_DISABLE"] = "1"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

        # 1. fastembed — synchronous, must run in main thread
        try:
            from app.rag.embedder import embed_query
            embed_query("startup warmup", _s)
            get_logger().info("startup_embed_warmup_done", model=_s.EMBEDDING_MODEL)
        except Exception as exc:
            get_logger().warning("startup_embed_warmup_failed", error=str(exc))

        # 2. Reranker — loads lazily on first query. Disabled on Python 3.13+
        #    due to native crash in sentence-transformers with non-TTY stdout.
        #    Set GEMINIRAG_RERANKER=1 to force-enable (Docker / Python 3.11 only).
        import sys as _sys
        if _sys.version_info >= (3, 13):
            get_logger().info("startup_reranker_disabled",
                              reason="python_313_compat",
                              override_env="GEMINIRAG_RERANKER=1")

        get_logger().info("startup_complete")

    @app.get("/health")
    def health():
        from app.models.db import get_engine
        from sqlalchemy import text as _text

        checks: dict[str, str] = {}

        # DB check
        try:
            with get_engine().connect() as conn:
                conn.execute(_text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"unreachable: {exc}"

        # ChromaDB check
        try:
            from app.rag.vectorstore import get_chroma_client
            get_chroma_client(settings).heartbeat()
            checks["chromadb"] = "ok"
        except Exception as exc:
            checks["chromadb"] = f"unreachable: {exc}"

        all_ok = all(v == "ok" for v in checks.values())
        status_code = 200 if all_ok else 503
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"status": "ok" if all_ok else "degraded", **checks},
            status_code=status_code,
        )

    return app


app = create_app()

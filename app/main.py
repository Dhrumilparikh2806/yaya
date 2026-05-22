import time
import uuid as _uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.limiter import limiter
from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import configure_tracing
from app.api import auth, files, jobs, query, documents, admin


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="GeminiRAG", version="1.0.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
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
        get_logger().info(
            "http_request",
            request_id=request_id,
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

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

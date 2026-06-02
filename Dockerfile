########################################################################
# GeminiRAG — Hugging Face Spaces Dockerfile
#
# All services run inside one container managed by supervisord:
#   • Redis (in-process, port 6379)
#   • ChromaDB HTTP server (in-process, port 8001)
#   • FastAPI (port 7860 — HF Spaces public port)
#   • Celery worker (background)
#
# External dependencies (set as HF Space Secrets):
#   DATABASE_URL  →  Neon.tech free PostgreSQL
#   GROQ_API_KEY  →  console.groq.com (free)
#   SECRET_KEY    →  random 48-char string
########################################################################

FROM python:3.11-slim

# ── System deps ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ffmpeg \
    libsndfile1 \
    redis-server \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ──────────────────────────────────────────────────────
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# ── App code ─────────────────────────────────────────────────────────
COPY . .

# ── Supervisor config ────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/conf.d/geminirag.conf

# ── Entrypoint ───────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persistent storage for ChromaDB vectors and uploaded files
RUN mkdir -p /data/chroma /data/uploads

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]

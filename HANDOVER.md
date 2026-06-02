# GeminiRAG — Handover Document

**Project:** GeminiRAG — Multimodal RAG Pipeline  
**Delivered by:** Dhrumil Parikh  
**Delivery date:** 3 June 2026  
**Client:** MasterCRM Internal Engineering

---

## How to Run the System

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | 3.13 disables cross-encoder reranker (safe, falls back gracefully) |
| Node.js 18+ | Frontend only |
| PostgreSQL 16 | Native install or Docker |
| Redis 7+ | Docker recommended |
| ChromaDB 0.5+ | Must run as HTTP server on port 8001 |
| Groq API key | Free tier is sufficient for development |
| Gemini API key | Optional — only needed for `/v1/query/stream` SSE endpoint |

### First-time setup

```bash
# 1. Copy and fill environment file
cp .env.example .env
# Required keys: GROQ_API_KEY, SECRET_KEY, DATABASE_URL, REDIS_URL
# See .env.example for all options

# 2. Start Redis and ChromaDB
docker compose up -d redis chromadb

# 3. Create the PostgreSQL database (skip if using Docker Compose postgres service)
createdb geminirag && createuser geminirag --password geminirag

# 4. Install Python dependencies
pip install -e .

# 5. Run migrations
alembic upgrade head

# 6. Seed admin user
py scripts/seed_admin.py --email admin@mastercrm.com --password YourSecurePass!

# 7. API server (terminal 1)
py -m uvicorn app.main:app --reload --port 8000

# 8. Celery worker (terminal 2)
py -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo

# 9. Frontend (terminal 3)
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

### Production (Docker)

```bash
# Set ALLOWED_ORIGINS=https://your-domain.com in .env first
docker compose -f docker-compose.prod.yml up --build
```

---

## Admin Credentials

```bash
# Create or update an admin user
py scripts/seed_admin.py --email demo@mastercrm.com --password Demo2026!

# To reset: delete the row in PostgreSQL and re-run
DELETE FROM users WHERE email = 'demo@mastercrm.com';
```

---

## LLM Configuration

| Role | Model | Env var |
|---|---|---|
| RAG answer generation | `llama-3.3-70b-versatile` | `GROQ_MODEL` |
| File extraction / summaries / RAGAS | `llama-3.1-8b-instant` | `GROQ_PROCESSING_MODEL` |
| Image OCR / video frames | `meta-llama/llama-4-scout-17b-16e-instruct` | `GROQ_VISION_MODEL` |
| Speech-to-text | `whisper-large-v3` | `WHISPER_MODEL` |
| Streaming query (optional) | `gemini-2.0-flash` | `GEMINI_MODEL` |
| Agent synthesis | `llama-3.1-8b-instant` | hardcoded in `agent/agent.py` |
| Embeddings | `BAAI/bge-small-en-v1.5` (local) | `EMBEDDING_MODEL` |

All Groq calls are logged to `usage_logs` with prompt tokens, completion tokens, and latency.

---

## RAGAS Baseline Evaluation

```bash
# 1. Create a test set
cat > /tmp/ragas_test_set.json << 'EOF'
[
  {
    "question": "What is the main topic of the document?",
    "ground_truth": "The document covers...",
    "job_id": "<UUID of a completed job>"
  }
]
EOF

# 2. Run baseline
py scripts/ragas_baseline.py --test-set /tmp/ragas_test_set.json
# → /tmp/ragas_baseline.json
```

**Delivery targets:** Faithfulness ≥ 0.80 · Answer Relevancy ≥ 0.75 · Context Precision ≥ 0.70

---

## Key Source Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI factory, middleware, model warmup |
| `app/config.py` | All env vars with startup validation |
| `app/models/db.py` | ORM tables (User, Job, UsageLog, QueryHistory) |
| `app/api/files.py` | Upload endpoint, file type dispatch |
| `app/api/query.py` | RAG query (JSON + SSE streaming) |
| `app/api/admin.py` | Usage stats, RAGAS trends, user management |
| `app/processors/base.py` | Abstract processor, Groq LLM helpers |
| `app/processors/audio_utils.py` | Whisper transcription + SpeechBrain diarization |
| `app/rag/engine.py` | Hybrid search, confidence gate, Groq answer |
| `app/rag/chunker.py` | Hierarchical (parent/child) chunking |
| `app/rag/vectorstore.py` | ChromaDB helpers + RRF merge |
| `app/rag/bm25_index.py` | BM25 index (Redis-cached) |
| `app/rag/reranker.py` | Cross-encoder reranker |
| `app/agent/agent.py` | Intent classification + Groq synthesis |
| `app/agent/tools.py` | ingest, status, query, list, summarize tools |
| `app/workers/tasks.py` | process_file, compute_ragas, cleanup_old_uploads |
| `app/evaluation/ragas_eval.py` | RAGAS metric computation |
| `scripts/seed_admin.py` | Create initial admin user |
| `scripts/seed_ragas_scores.py` | Seed day-by-day RAGAS demo data |
| `scripts/ragas_baseline.py` | Offline RAGAS baseline evaluation |

---

## Adding a New File Type

1. Create `app/processors/newtype.py` extending `BaseProcessor` — implement `extract()` and `summarise()`.
2. Add the extension(s) to `EXTENSION_MAP` in `app/api/files.py`.
3. Add the dispatch case to `process_file()` in `app/workers/tasks.py`.
4. Add the extension to the accepted types list in `frontend/src/pages/UploadPage.tsx`.
5. Add tests in `tests/test_processors.py`.

---

## Job Processing Pipeline

```
Upload → Job(PENDING) → Celery enqueue
  → PROCESSING / extracting  — processor.extract()
  → PROCESSING / summarising — processor.summarise() + Groq LLM
  → PROCESSING / chunking    — chunk_markdown_hierarchical()
  → PROCESSING / embedding   — embed_chunks() via fastembed (local)
  → PROCESSING / indexing    — ChromaDB upsert + BM25 invalidate
  → COMPLETED (chunk_count set)

On retryable error (rate limit, unknown):
  → FAILED → re-enqueue (60 × 2ⁿ s) → repeat up to 3×
  → FAILED_PERMANENT + Redis dead-letter queue

Speaker embeddings (audio/video only):
  SpeechBrain ECAPA mean embedding per speaker attached as
  speaker_embedding_json metadata on each ChromaDB chunk.
```

---

## Known Limitations

1. **Speaker diarization accuracy** depends on audio quality. Mono recordings with minimal background noise and clearly distinct voices produce the best results. Overlapping speech is not supported.

2. **Large video files (> 500 MB)** are rejected at upload. Near-duplicate frame skipping (> 98 % histogram similarity) reduces the number of frames processed.

3. **RAGAS token cost** — every RAG query triggers a background RAGAS evaluation that calls the Groq LLM again. At high query volumes this can be significant. Disable by removing `compute_ragas.delay(str(qh.id))` in `app/rag/engine.py`.

4. **ChromaDB persistence** — embeddings live in a Docker named volume. Deleting the volume loses all vectors; documents must be re-uploaded and re-processed. Back up the `chromadata` Docker volume before infrastructure changes.

5. **Agent LLM window** — the last 10 conversation turns are sent to Groq; full history is stored in Redis for 7 days but not included in the LLM context after 10 turns.

6. **Reranker on Python 3.13+** — disabled by default due to native tokenizer crash. Set `GEMINIRAG_RERANKER=1` to force-enable (Python 3.11 / Docker only).

7. **Streaming query requires Gemini** — `POST /v1/query/stream` uses the Gemini SDK for SSE streaming. Set `GEMINI_API_KEY` to use it. The standard `POST /v1/query` always uses Groq and does not require a Gemini key.

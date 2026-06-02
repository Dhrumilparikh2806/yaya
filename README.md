# GeminiRAG

A production-ready multimodal Retrieval-Augmented Generation (RAG) pipeline. Accepts PDF, DOCX, XLSX, CSV, image, audio, and video uploads; extracts and chunks content with Groq LLMs; stores embeddings in ChromaDB; and answers natural-language questions with cited, confidence-gated responses.

Includes a Groq-powered conversational agent with Redis-backed session history, a React/TypeScript admin dashboard, structured JSON observability, RAGAS quality evaluation on every query, and per-user token cost tracking.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      React Frontend (Vite)                        │
│        Login / Upload / Query / Jobs / Agent / Admin             │
└───────────────────────────┬──────────────────────────────────────┘
                            │  HTTP · Bearer JWT
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI  :8000                                 │
│  /auth  /v1/files  /v1/query  /v1/jobs  /v1/agent  /v1/admin    │
│  slowapi rate-limiting · structlog JSON · OpenTelemetry traces   │
└──────┬────────────────┬──────────────────────┬───────────────────┘
       │                │                      │
       ▼                ▼                      ▼
┌────────────┐  ┌──────────────┐   ┌──────────────────────────┐
│ PostgreSQL │  │ Redis        │   │ ChromaDB  :8001           │
│  users     │  │  task queue  │   │  geminirag_chunks         │
│  jobs      │  │  BM25 cache  │   │  (cosine similarity)      │
│  usage_logs│  │  agent sess. │   └──────────────────────────┘
│  query_hist│  └──────┬───────┘              ▲
└────────────┘         │                      │ BAAI/bge-small-en
                       ▼                      │ embeddings (local)
               ┌──────────────┐               │
               │ Celery Worker│───────────────┘
               │              │
               │  extract     │──► Groq Whisper  (audio/video)
               │  summarise   │──► Groq LLM      (text processing)
               │  chunk       │──► Groq Vision   (images/frames)
               │  embed       │──► fastembed     (local, no API)
               │  index       │
               └──────────────┘

Query path (per request):
  question → embed → vector search + BM25 → RRF merge
           → cross-encoder rerank → confidence gate
           → Groq LLM (answer) → save QueryHistory
           → async RAGAS evaluation (Celery)

Agent path:
  message → intent classify → ChromaDB retrieve
          → Groq LLM synthesis → Redis session persist
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.111+ |
| Primary LLM | Groq — `llama-3.3-70b-versatile` (RAG / agent) |
| Processing LLM | Groq — `llama-3.1-8b-instant` (extraction, summaries, RAGAS) |
| Vision LLM | Groq — `meta-llama/llama-4-scout-17b-16e-instruct` (images, frames) |
| Speech-to-text | Groq Whisper — `whisper-large-v3` (audio / video) |
| Speaker diarization | SpeechBrain ECAPA-VOXCELEB (local model) |
| Embeddings | BAAI/bge-small-en-v1.5 via fastembed (local, no API cost) |
| Vector store | ChromaDB (HTTP, cosine similarity) |
| Sparse retrieval | BM25 (built from ChromaDB data, cached in Redis) |
| Reranker | sentence-transformers cross-encoder (local) |
| Task queue | Celery 5.3+ + Redis |
| Database | PostgreSQL 16 + SQLModel + Alembic |
| RAG evaluation | RAGAS (async, per query) |
| Observability | structlog (JSON) + OpenTelemetry |
| Auth | JWT HS256 (python-jose) + bcrypt |
| Rate limiting | slowapi |
| Streaming query | Gemini API (optional — `GEMINI_API_KEY` required only for `/v1/query/stream`) |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS + Recharts |
| Containerisation | Docker + Docker Compose |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.13 disables the cross-encoder reranker |
| Node.js | 18+ | Frontend only |
| PostgreSQL | 16 | Can run native or via Docker |
| Redis | 7+ | Celery broker + BM25 cache + agent sessions |
| ChromaDB | 0.5+ | Must run as HTTP server on port 8001 |
| Groq API key | — | Required — free tier sufficient for dev |
| Gemini API key | — | Optional — only needed for `/v1/query/stream` |

---

## Setup

### Local development

```bash
# 1. Copy and fill in the environment file
cp .env.example .env
# Required: GROQ_API_KEY, SECRET_KEY, DATABASE_URL, REDIS_URL
# See "Environment Variables" section below

# 2. Start Redis and ChromaDB
docker compose up -d redis chromadb

# 3. Create the PostgreSQL database (if not using Docker)
createdb geminirag
createuser geminirag --password geminirag

# 4. Install Python dependencies
pip install -e .

# 5. Run database migrations
alembic upgrade head

# 6. Seed an admin user
py scripts/seed_admin.py --email admin@example.com --password changeme

# 7. Start the API server  (terminal 1)
py -m uvicorn app.main:app --reload --port 8000

# 8. Start the Celery worker  (terminal 2)
py -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo

# 9. Start the frontend  (terminal 3)
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

### Docker (all-in-one)

```bash
docker compose up --build
# API → http://localhost:8000
# Frontend → http://localhost:5173
```

Production:

```bash
docker compose -f docker-compose.prod.yml up --build
```

---

## Environment Variables

### Required (P0)

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key — used for all LLM and Whisper calls |
| `SECRET_KEY` | JWT signing secret — minimum 32 random characters |
| `DATABASE_URL` | PostgreSQL connection string e.g. `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string e.g. `redis://localhost:6379/0` |

### Optional (P1 — defaults provided)

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | `""` | Required only for `/v1/query/stream` (SSE streaming) |
| `CHROMA_HOST` | `localhost` | ChromaDB server host |
| `CHROMA_PORT` | `8001` | ChromaDB server port |
| `CHROMA_COLLECTION` | `geminirag_chunks` | ChromaDB collection name |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated CORS origins |
| `UPLOAD_DIR` | `/tmp/geminirag_uploads` | File storage root |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT lifetime |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model for RAG answer generation |
| `GROQ_PROCESSING_MODEL` | `llama-3.1-8b-instant` | Model for extraction, summaries, RAGAS |
| `GROQ_VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Model for image/frame OCR |
| `WHISPER_MODEL` | `whisper-large-v3` | Model for audio transcription |
| `WHISPER_LANGUAGE` | `""` | Force Whisper language (e.g. `en`). Empty = auto-detect |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model (runs locally) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model for SSE streaming |
| `CHUNK_SIZE` | `600` | Parent chunk size in words |
| `CHILD_CHUNK_SIZE` | `150` | Child chunk size in words (indexed in ChromaDB) |
| `CHUNK_OVERLAP` | `50` | Overlap in words between chunks |
| `RAG_TOP_K` | `8` | Chunks retrieved per query |
| `CONFIDENCE_THRESHOLD` | `0.4` | Min cosine similarity to pass the confidence gate |
| `DIARIZATION_THRESHOLD` | `0.4` | AgglomerativeClustering distance threshold for speakers |
| `VIDEO_FRAME_INTERVAL` | `60` | Seconds between extracted video frames |
| `MAX_AUDIO_CHUNK_MB` | `20` | Max audio chunk size before splitting for Whisper |
| `CELERY_MAX_RETRIES` | `3` | Max Celery task retry attempts |
| `CELERY_RETRY_BACKOFF` | `60` | Base seconds for exponential retry backoff |
| `OTEL_SERVICE_NAME` | `geminirag` | OpenTelemetry service name |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | none | Create user account (`role`: `user` or `admin`) |
| `POST` | `/auth/login` | none | Obtain JWT — rate-limited 10/min |
| `POST` | `/v1/files/upload` | user | Upload file, enqueue processing job |
| `GET` | `/v1/jobs` | user | List all jobs |
| `GET` | `/v1/jobs/{id}` | user | Get job status and step |
| `POST` | `/v1/jobs/{id}/reprocess` | user | Re-queue a job |
| `GET` | `/v1/documents` | user | List completed documents (chunk_count > 0) |
| `GET` | `/v1/documents/{id}/summary` | user | Structured summary JSON from processor |
| `POST` | `/v1/query` | user | RAG query — returns answer + citations + RAGAS |
| `POST` | `/v1/query/stream` | user | Streaming RAG via SSE (requires `GEMINI_API_KEY`) |
| `POST` | `/v1/agent/chat` | user | Multi-turn agent conversation |
| `DELETE` | `/v1/agent/session/{id}` | user | Clear agent session history |
| `GET` | `/v1/admin/usage` | admin | Token/latency stats by day, user, endpoint |
| `GET` | `/v1/admin/ragas` | admin | RAGAS metric averages and 7-day trends |
| `GET` | `/v1/admin/users` | admin | All users with query/token/job counts |
| `PATCH` | `/v1/admin/users/{id}` | admin | Toggle user `is_active` |
| `GET` | `/v1/admin/logs` | admin | Raw `UsageLog` entries (filterable) |
| `GET` | `/health` | none | DB + ChromaDB liveness check |

### Example: Register and log in

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Str0ng!", "role": "user"}'

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Str0ng!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Example: Upload a file

```bash
curl -X POST http://localhost:8000/v1/files/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf"
# → {"job_id": "...", "filename": "report.pdf", "file_type": "pdf", "status": "PENDING"}
```

### Example: Poll job until complete

```bash
curl http://localhost:8000/v1/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
# → {"status": "COMPLETED", "step": "completed", "chunk_count": 14, ...}
```

### Example: RAG query

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What were the key findings?", "job_ids": ["<JOB_ID>"]}'
# → {"answer": "...[1]...", "citations": [...], "confidence_gate_passed": true, ...}
```

### Example: Agent chat

```bash
curl -X POST http://localhost:8000/v1/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "How many documents are in the system?"}'
```

---

## Supported File Types

| Type | Extensions | Processing |
|---|---|---|
| PDF | `.pdf` | Page-by-page text + table extraction (pdfplumber) |
| DOCX | `.docx` | Paragraph, heading, and table extraction (python-docx) |
| XLSX / CSV | `.xlsx`, `.csv` | Multi-sheet markdown tables (openpyxl / pandas) |
| Image | `.png`, `.jpg`, `.jpeg`, `.webp` | OCR + visual description (Groq Vision) |
| Audio | `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.webm` | Whisper transcription + SpeechBrain ECAPA speaker diarization |
| Video | `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, `.webm` | Audio track → audio pipeline; frames → image pipeline (saved to disk, processed with OCR prompt) |

Max upload size: **500 MB**.

---

## RAG Pipeline Details

### Hierarchical Chunking

Documents are split at H2 headings into sections. Each section produces two levels:

- **Parent chunks** (600 words, 50-word overlap) — sent to the LLM as answer context
- **Child chunks** (150 words, 20-word overlap) — embedded and indexed in ChromaDB

At retrieval time, ChromaDB matches child chunks (precise), then the parent text is returned to the LLM (richer context).

### Hybrid Search

Each query runs two parallel retrievals:

1. **Vector search** — cosine similarity via ChromaDB on child chunk embeddings
2. **BM25 sparse search** — TF-IDF over the same chunks (index cached in Redis)

Results are merged with **Reciprocal Rank Fusion** (k = 60), then re-ranked by a **cross-encoder** (sentence-transformers) for a final relevance ordering.

### Confidence Gate

The top cosine similarity score from vector search is compared against `CONFIDENCE_THRESHOLD`. If it falls below the threshold, the LLM is never called and the response is `"I couldn't find sufficiently relevant information…"`. This prevents hallucinated answers when no relevant content exists.

### Audio / Video Speaker Embeddings

After diarization, the ECAPA model produces a 192-dimensional speaker embedding for each identified speaker. These embeddings are stored as `speaker_embedding_json` metadata on every ChromaDB chunk from that audio/video, enabling speaker-level filtering in future queries.

---

## RAGAS Evaluation

Every RAG query triggers an async RAGAS evaluation (via Celery). Scores are stored in `query_history.ragas_scores` and surfaced in the admin dashboard.

| Metric | Requires ground truth | Measures |
|---|---|---|
| Faithfulness | No | Answer is grounded in retrieved context |
| Answer Relevancy | No | Answer addresses the question |
| Context Precision | Yes | Retrieved chunks are relevant |
| Context Recall | Yes | Context covers ground truth information |
| Answer Correctness | Yes | Answer matches ground truth |

### Offline baseline evaluation

Create a test set at `/tmp/ragas_test_set.json`:

```json
[
  {
    "question": "What is the main topic?",
    "ground_truth": "The document covers ...",
    "job_id": "<JOB_UUID>"
  }
]
```

Run:

```bash
py scripts/ragas_baseline.py --test-set /tmp/ragas_test_set.json
# → /tmp/ragas_baseline.json
```

Target baselines: Faithfulness ≥ 0.80, Answer Relevancy ≥ 0.75, Context Precision ≥ 0.70.

---

## Scripts

| Script | Purpose |
|---|---|
| `scripts/seed_admin.py` | Create an initial admin user |
| `scripts/seed_ragas_scores.py` | Seed day-by-day RAGAS dummy data for the admin dashboard |
| `scripts/ragas_baseline.py` | Run offline RAGAS evaluation against a test set |

```bash
# Seed admin user
py scripts/seed_admin.py --email admin@example.com --password MyPass!

# Seed RAGAS demo data (8 days, 2 rows/day)
py scripts/seed_ragas_scores.py --rows-per-day 2

# Baseline evaluation
py scripts/ragas_baseline.py --test-set /tmp/ragas_test_set.json
```

---

## Observability

All logs are structured JSON emitted by structlog. Key events:

| Event | Key Fields | When |
|---|---|---|
| `http_request` | `request_id`, `user_id`, `endpoint`, `method`, `status_code`, `latency_ms` | Every API request |
| `file_uploaded` | `user_id`, `filename`, `file_type`, `job_id`, `file_size_bytes` | On upload |
| `job_state_change` | `job_id`, `from_status`, `to_status`, `step`, `retry_count` | Every job transition |
| `llm_call` | `endpoint`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `job_id` | Every Groq/Gemini/Whisper call |
| `rag_query` | `question`, `retrieved_chunk_count`, `avg_similarity_score`, `latency_ms` | Every RAG query |
| `ragas_computed` | `query_id`, `faithfulness`, `answer_relevancy` | After async RAGAS completes |
| `agent_run_complete` | `user_id`, `session_id`, `intent`, `tool_call_count`, `prompt_tokens` | End of every agent turn |
| `diarization_complete` | `speaker_count` | After audio diarization |
| `ecapa_speaker_embeddings_computed` | `speaker_count` | After SpeechBrain embeddings computed |

Filter logs by job ID:

```bash
# Uvicorn / Docker logs
docker compose logs api | python -c "
import sys, json
for line in sys.stdin:
    try:
        e = json.loads(line)
        if e.get('job_id') == 'YOUR_JOB_ID':
            print(json.dumps(e, indent=2))
    except: pass
"
```

Every LLM call is also persisted to the `usage_logs` table with full token and latency detail, visible at `GET /v1/admin/logs`.

---

## Database Schema

| Table | Purpose |
|---|---|
| `users` | Accounts — email, hashed password, role, active flag |
| `jobs` | Processing jobs — status, step, retry count, error info, chunk count |
| `usage_logs` | Every LLM/Whisper/embed API call — model, tokens, latency |
| `query_history` | Every RAG query — answer, citations, scores, RAGAS results |

---

## Job State Machine

```
PENDING → PROCESSING → COMPLETED
               │
               └─► FAILED  (retryable, retry_count < 3)
                      │
                      └─► PENDING  (re-enqueued, 60 × 2ⁿ s backoff)
                             │  (after 3 attempts)
                             └─► FAILED_PERMANENT → Redis dead-letter queue
```

Processing steps written to `jobs.step`:
`queued` → `extracting` → `summarising` → `chunking` → `embedding` → `indexing` → `completed`

---

## Known Limitations

- **Speaker diarization accuracy** depends on audio quality. Mono recordings with low background noise and distinct voices produce the best results.
- **Large video files** (> 500 MB) are rejected at upload. Near-duplicate frame skipping (> 98 % histogram similarity) reduces processing time.
- **RAGAS token cost** — every RAG query triggers a background RAGAS evaluation. At high query volume this doubles token usage. Remove the `compute_ragas.delay()` call in `app/rag/engine.py` to disable.
- **ChromaDB persistence** — the default dev setup stores embeddings in a Docker volume. Deleting the volume loses all embeddings; documents must be re-uploaded.
- **Agent session window** — the LLM context is capped at the last 10 messages. Full history is persisted in Redis for 7 days but only the last 10 turns are sent to the model.
- **Reranker on Python 3.13+** — the sentence-transformers cross-encoder is disabled on Python 3.13 due to a native tokenizer crash. Results fall back to RRF-ranked order. Force-enable with `GEMINIRAG_RERANKER=1` on Python 3.11/Docker.
- **Streaming query requires Gemini** — `POST /v1/query/stream` (SSE) uses the Gemini SDK. Set `GEMINI_API_KEY` to use it; the standard `POST /v1/query` endpoint always uses Groq.

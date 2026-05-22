# GeminiRAG

GeminiRAG is a multimodal Retrieval-Augmented Generation (RAG) pipeline built with Google Gemini, FastAPI, ChromaDB, and Celery. It accepts PDF, DOCX, XLSX, CSV, image, video, and audio uploads, extracts and chunks content using Gemini multimodal models, stores embeddings in ChromaDB, and answers natural-language questions with cited, confidence-gated responses.

The system includes a Google ADK-powered conversational agent with five MCP tools, a full-featured React/TypeScript frontend, structured JSON observability logging, RAGAS evaluation metrics for every query, and an admin dashboard showing per-user token spend, endpoint latency, and RAGAS score trends.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│          Login / Upload / Query / Jobs / Agent / Admin          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (Axios + Bearer JWT)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI (port 8000)                         │
│  /auth  /v1/files  /v1/query  /v1/jobs  /v1/agent  /v1/admin   │
│  slowapi rate limiting · structlog JSON · OpenTelemetry traces  │
└──────┬──────────────┬─────────────────────┬─────────────────────┘
       │              │                     │
       ▼              ▼                     ▼
┌────────────┐ ┌────────────────┐  ┌───────────────────────┐
│ PostgreSQL │ │  Redis (queue) │  │  ChromaDB (vectors)   │
│  jobs      │ │                │  │  geminirag_chunks      │
│  users     │ └───────┬────────┘  └───────────────────────┘
│  usage_logs│         │                     ▲
│  query_hist│         ▼                     │
└────────────┘ ┌────────────────┐   embeddings│
               │ Celery Worker  │             │
               │                │─────────────┘
               │  extract text  │
               │  chunk content │
               │  call Gemini   │──► Gemini API (multimodal)
               │  embed chunks  │
               └────────────────┘

               ┌────────────────────────────────┐
               │  Google ADK Agent              │
               │  POST /v1/agent/chat           │
               │  Tools: ingest_file            │
               │         get_job_status         │
               │         query_rag              │
               │         list_documents         │
               │         summarize_document     │
               └────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| Docker Desktop | latest |
| Gemini API key | from [aistudio.google.com](https://aistudio.google.com) |

---

## Setup

```bash
# 1. Clone
git clone <repo-url>
cd geminirag

# 2. Create environment file
cp .env.example .env
# Edit .env and fill in:
#   GEMINI_API_KEY=your_key_here
#   SECRET_KEY=a_long_random_string
#   DATABASE_URL=postgresql://geminirag:geminirag@localhost:5432/geminirag
#   REDIS_URL=redis://localhost:6379/0

# 3. Start infrastructure
docker compose up -d postgres redis chromadb

# 4. Install Python dependencies
pip install -e .

# 5. Run database migrations
alembic upgrade head

# 6. Start the API server
uvicorn app.main:app --reload --port 8000

# 7. Start the Celery worker (separate terminal)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

Or start everything via Docker:

```bash
docker compose up --build
```

---

## Running the Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | yes | — | Google Gemini API key |
| `SECRET_KEY` | yes | — | JWT signing secret (min 32 chars) |
| `DATABASE_URL` | yes | — | PostgreSQL connection string |
| `REDIS_URL` | yes | — | Redis connection string |
| `CHROMA_HOST` | no | `localhost` | ChromaDB host |
| `CHROMA_PORT` | no | `8001` | ChromaDB port |
| `ALLOWED_ORIGINS` | no | `http://localhost:5173` | Comma-separated CORS origins |
| `GEMINI_MODEL` | no | `gemini-2.0-flash` | Gemini model for processing |
| `GEMINI_EMBEDDING_MODEL` | no | `models/text-embedding-004` | Embedding model |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | `60` | JWT lifetime |
| `RAG_TOP_K` | no | `5` | Number of chunks retrieved per query |
| `CONFIDENCE_THRESHOLD` | no | `0.65` | Min score to pass confidence gate |
| `UPLOAD_DIR` | no | `/tmp/geminirag_uploads` | File storage path |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | none | Create user account |
| `POST` | `/auth/login` | none | Obtain JWT (rate-limited: 10/min) |
| `POST` | `/v1/files/upload` | user | Upload a file, enqueue processing job |
| `GET` | `/v1/jobs` | user | List jobs (user sees own; admin sees all) |
| `GET` | `/v1/jobs/{id}` | user | Get single job status |
| `GET` | `/v1/documents` | user | List completed documents |
| `GET` | `/v1/documents/{id}/summary` | user | Get document summary |
| `POST` | `/v1/query` | user | RAG query with citations and RAGAS scores |
| `POST` | `/v1/agent/chat` | user | ADK agent conversation turn |
| `GET` | `/v1/admin/usage` | admin | Token usage stats by day/user/endpoint |
| `GET` | `/v1/admin/ragas` | admin | RAGAS metric averages and trends |
| `GET` | `/v1/admin/users` | admin | All users with query/token/job counts |
| `PATCH` | `/v1/admin/users/{id}` | admin | Toggle user active/inactive |
| `GET` | `/v1/admin/logs` | admin | Raw usage log entries |
| `GET` | `/health` | none | Health check |

### Example: Upload a file

```bash
curl -X POST http://localhost:8000/v1/files/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf"
# → {"job_id": "...", "filename": "report.pdf", "file_type": "pdf", "status": "PENDING"}
```

### Example: RAG query

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What were the main findings?", "job_ids": ["..."]}'
```

### Example: Agent chat

```bash
curl -X POST http://localhost:8000/v1/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Ingest /tmp/geminirag_uploads/abc/report.pdf and summarise it"}'
```

---

## Supported File Types

| Type | Extensions | Processing |
|---|---|---|
| PDF | `.pdf` | Text extraction + page chunking |
| DOCX | `.docx` | Paragraph + heading extraction |
| XLSX / CSV | `.xlsx`, `.csv` | Sheet analysis, key insights |
| Image | `.png`, `.jpg`, `.jpeg`, `.webp` | OCR + visual description |
| Video | `.mp4`, `.mov` | Frame + audio extraction, diarization |
| Audio | `.mp3`, `.wav`, `.m4a` | Transcript + speaker diarization |

---

## Running RAGAS Offline Evaluation

Create a test set file at `/tmp/ragas_test_set.json`:

```json
[
  {
    "question": "What is the main topic of the document?",
    "ground_truth": "The document covers...",
    "job_id": "your-job-uuid"
  }
]
```

Then run:

```bash
python scripts/ragas_baseline.py --test-set /tmp/ragas_test_set.json
# Results saved to /tmp/ragas_baseline.json
```

RAGAS metrics computed:
- **Faithfulness** — answer is grounded in retrieved context
- **Answer Relevancy** — answer addresses the question
- **Context Precision** — retrieved chunks are relevant
- **Context Recall** — context covers the ground truth
- **Answer Correctness** — answer matches ground truth

---

## Seeding an Admin User

```bash
python scripts/seed_admin.py --email admin@example.com --password changeme
```

---

## Observability Guide

All logs are emitted as structured JSON via structlog. Key event types:

| Event | Fields | When |
|---|---|---|
| `http_request` | `request_id`, `user_id`, `endpoint`, `method`, `status_code`, `latency_ms` | Every API request |
| `file_uploaded` | `user_id`, `filename`, `file_type`, `job_id`, `file_size_bytes` | On upload |
| `job_state_change` | `job_id`, `status`, `step`, `user_id` | Every job status transition |
| `gemini_call` | `job_id`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms` | Every Gemini API call |
| `rag_query` | `user_id`, `question_preview`, `num_chunks`, `confidence`, `latency_ms` | Every RAG query |
| `tool_call` | `tool_name`, `latency_ms`, `result_preview` | Every ADK agent tool use |
| `ragas_eval` | `query_id`, `faithfulness`, `answer_relevancy`, `latency_ms` | After RAGAS eval completes |

To filter logs by job:
```bash
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

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.111 |
| AI / LLM | Google Gemini 2.0 Flash (`google-genai`) |
| Agent framework | Google ADK 2.0 |
| Vector store | ChromaDB |
| Embeddings | `models/text-embedding-004` |
| Task queue | Celery + Redis |
| Database | PostgreSQL 16 + SQLModel + Alembic |
| RAG evaluation | RAGAS |
| Observability | structlog JSON + OpenTelemetry |
| Rate limiting | slowapi |
| Auth | JWT (python-jose + bcrypt) |
| Frontend framework | React 18 + TypeScript + Vite |
| Frontend styling | TailwindCSS v3 |
| Frontend charts | Recharts |
| HTTP client | Axios |
| Containerisation | Docker + Docker Compose |

---

## Known Limitations

- **Speaker diarization accuracy** depends on audio quality; close-mic recordings with low background noise produce the best results. The Gemini diarization prompt may merge speakers if voices are similar.
- **Large video files** (>500 MB) are rejected at upload. Processing very large files may hit Gemini's context window limits for frame extraction.
- **RAGAS adds token cost** — every query triggers a background RAGAS evaluation that calls Gemini again. At high query volume this can be significant. Disable by removing the background task in `app/api/query.py` if cost is a concern.
- **ChromaDB persistence** — in the default dev setup ChromaDB data lives in a Docker volume. If the volume is deleted, all embeddings are lost and documents must be re-uploaded.
- **In-memory agent sessions** — ADK sessions use `InMemorySessionService`, so agent conversation history is lost on server restart.

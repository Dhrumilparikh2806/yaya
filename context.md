# GeminiRAG — Project Context
**For use by the next chat session to resume work without losing any context.**

---

## What This Project Is

GeminiRAG is a **production-ready Multimodal RAG (Retrieval-Augmented Generation) pipeline** built for MasterCRM Internal Engineering. It allows users to upload any document (PDF, Word, Excel, CSV, image, audio, video), have it processed by Google Gemini, chunked and embedded into a ChromaDB vector store, and then queried in natural language. The system returns answers with citations and RAGAS quality scores.

**Delivered by:** Dhrumil Parikh  
**Delivery date:** 3 June 2026  
**GitHub repo:** https://github.com/Dhrumilparikh2806/yaya (branch: master)

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM / Embeddings | Google Gemini (`gemini-2.5-flash`, `models/gemini-embedding-001`) via `google-genai` SDK |
| Agent | Google ADK (`google-adk`) with 5 MCP tools |
| API | FastAPI 0.111 + uvicorn, Python 3.11 |
| Task Queue | Celery 5.6 + Redis broker, PostgreSQL result backend |
| Vector Store | ChromaDB (HTTP client, cosine similarity) |
| Database | PostgreSQL 18 (native, NOT Docker) — SQLModel + Alembic |
| RAG Evaluation | RAGAS (faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness) |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS + Recharts |
| Observability | structlog (JSON), OpenTelemetry (stdout exporter), UsageLog DB table |
| Auth | JWT (HS256, python-jose) + bcrypt passwords |
| Rate Limiting | slowapi (10/min on /auth/login) |

---

## Environment (Local, No Docker)

**Important:** Docker is NOT installed on this machine. All services run natively.

| Service | Port | Status | Notes |
|---|---|---|---|
| PostgreSQL 18 | 5432 | Running natively | DB: `geminirag`, user: `geminirag`, pass: `geminirag` |
| Redis | 6379 | Running natively | |
| ChromaDB | 8001 | Running natively | |
| FastAPI (uvicorn) | 8000 | Must be started manually | See "How to Start" below |
| Celery worker | — | Must be started manually | Uses `--pool=solo` on Windows |
| React (Vite) | 5173 | Must be started manually | |

### How to Start Everything

Open 3 separate cmd windows (or use PowerShell `Start-Process`):

**Window 1 — API Server:**
```
cd "c:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag"
py -m uvicorn app.main:app --reload --port 8000
```

**Window 2 — Celery Worker:**
```
cd "c:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag"
py -m celery -A app.workers.celery_app worker --loglevel=info --concurrency=2 --pool=solo
```

**Window 3 — Frontend:**
```
cd "c:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag\frontend"
npm run dev
```

Or via PowerShell (each in its own visible cmd window that stays alive):
```powershell
Start-Process cmd.exe -ArgumentList "/k", "cd /d `"...\geminirag`" && py -m uvicorn app.main:app --reload --port 8000"
Start-Process cmd.exe -ArgumentList "/k", "cd /d `"...\geminirag\frontend`" && npm run dev"
```

### Verification
```powershell
# Check health (should return {"status":"ok","database":"ok","chromadb":"ok"})
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing | Select -Expand Content
```

---

## .env File Location and Contents

Path: `c:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag\.env`

```
GEMINI_API_KEY=AIzaSyD-0xYBLCksuwdk0oo1SO3S_gdFXW3DFNs
DATABASE_URL=postgresql://geminirag:geminirag@localhost:5432/geminirag
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=geminirag_secret_key_minimum_32_chars_long_secure
UPLOAD_DIR=C:/tmp/geminirag_uploads
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
```

`.env` is gitignored — never commit it.

---

## Database

- **Engine:** PostgreSQL 18, running on localhost:5432
- **Database:** `geminirag`
- **Tables:** `users`, `jobs`, `usage_logs`, `query_history`
- **Migrations:** Alembic (`alembic upgrade head`)
- **Connection pooling:** pool_size=10, max_overflow=20, pool_pre_ping=True (in `app/models/db.py`)

To view in PgAdmin: connect to localhost:5432, user=geminirag, password=geminirag, DB=geminirag.

---

## Admin Credentials

```
Email:    admin@test.com
Password: Admin1234!
Role:     admin
```

To recreate: `py scripts/seed_admin.py --email admin@test.com --password Admin1234!`

---

## API Overview

Base URL: `http://localhost:8000`  
Docs: `http://localhost:8000/docs`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /auth/register | No | Register user |
| POST | /auth/login | No | Login → JWT token |
| POST | /v1/files/upload | JWT | Upload file → returns job_id (async) |
| GET | /v1/jobs/{id} | JWT | Get job status |
| GET | /v1/jobs | JWT | List all user's jobs (admin sees all) |
| POST | /v1/jobs/{id}/reprocess | JWT | Re-queue failed job |
| GET | /v1/documents | JWT | List completed documents |
| GET | /v1/documents/{id}/summary | JWT | Get document AI summary |
| POST | /v1/query | JWT | RAG query → answer + citations |
| POST | /v1/query/stream | JWT | Streaming RAG via SSE |
| POST | /v1/agent/chat | JWT | ADK agent chat |
| GET | /v1/admin/usage | Admin | Usage stats |
| GET | /v1/admin/ragas | Admin | RAGAS metric averages |
| GET | /v1/admin/users | Admin | User list with stats |
| PATCH | /v1/admin/users/{id} | Admin | Toggle user is_active |
| GET | /health | No | DB + ChromaDB health check |

**Login format** (JSON body):
```json
{"email": "admin@test.com", "password": "Admin1234!"}
```

---

## File Processing Pipeline

```
User uploads file → POST /v1/files/upload
  → creates Job (PENDING) in PostgreSQL
  → saves file to C:/tmp/geminirag_uploads/{job_id}/
  → enqueues process_file.delay(job_id) in Celery via Redis

Celery worker picks up task → process_file(job_id):
  1. EXTRACTING  → dispatch to processor by file_type
                   (PDFProcessor / DOCXProcessor / XLSXProcessor /
                    ImageProcessor / VideoAudioProcessor)
                   → processor.extract() → raw text
                   → processor.summarise() → Gemini JSON summary
                   → stores summary in job.result

  2. CHUNKING    → chunk_text() or chunk_video_segments()
                   800 words/chunk, 100-word overlap, min 50 words

  3. EMBEDDING   → embed_chunks() → Gemini embedding API (768-dim)
                   batched 100 at a time, retry on 429

  4. INDEXING    → add_chunks() → ChromaDB upsert with 3x retry

  5. COMPLETED   → job.status = COMPLETED, job.chunk_count = N
```

**Supported file types:** PDF, DOCX, XLSX, CSV, PNG, JPG, JPEG, WEBP, MP4, MOV, MP3, WAV, M4A  
**Max file size:** 500 MB

---

## RAG Query Flow

```
POST /v1/query {question, job_ids?}
  1. Embed question → 768-dim vector (Gemini)
  2. Search ChromaDB → top_k=5 chunks (cosine similarity)
  3. Confidence gate: avg_score >= 0.65
     → If fails: return "I don't have enough information..."
  4. Format context from chunks
  5. Call Gemini (gemini-2.5-flash) with RAG system prompt
     → Answer must only use provided context, must cite [1][2]...
  6. Log to UsageLog + QueryHistory
  7. Enqueue compute_ragas.delay() async (adds ~15-60s, runs in background)
  8. Return: {answer, citations, confidence_gate_passed, avg_similarity_score}

RAGAS scores appear later in QueryHistory (populated by background Celery task)
```

Streaming variant: `POST /v1/query/stream` uses `StreamingResponse` with `text/event-stream`.  
Frontend uses Fetch API (not EventSource) because SSE doesn't support POST/auth headers.

---

## Celery Tasks

| Task | Trigger | Purpose |
|---|---|---|
| `process_file` | File upload | Full extraction → chunk → embed → index pipeline |
| `compute_ragas` | After each query | Async RAGAS score computation |
| `cleanup_old_uploads` | Daily (beat schedule) | Delete upload files for 7-day-old completed jobs |

**Retry strategy:** max_retries=3, exponential backoff (CELERY_RETRY_BACKOFF * 2^retry).  
**Dead letter queue:** FAILED_PERMANENT jobs pushed to Redis list `geminirag:dead_letter`.  
**Windows note:** Must use `--pool=solo` flag on Windows.

---

## ADK Agent

The agent has 5 tools and can hold multi-turn conversations:

| Tool | What it does |
|---|---|
| `ingest_file` | Upload a file by path → creates job, queues processing |
| `get_job_status` | Check processing status of a job |
| `query_rag` | Ask a question against uploaded documents |
| `list_documents` | List all completed documents |
| `summarize_document` | Get AI summary of a specific document |

**Session service:** InMemorySessionService — conversation history resets on server restart.  
**Production note:** Should be replaced with Redis/PostgreSQL-backed session service.

---

## RAGAS Evaluation

**Target scores (from spec):**
- Faithfulness ≥ 0.80
- Context Precision ≥ 0.60

**Running baseline offline:**
1. Ensure documents are uploaded and COMPLETED
2. Create test set JSON: `C:/tmp/ragas_test_set.json`
   ```json
   [{"question": "...", "ground_truth": "...", "job_id": "uuid-here"}]
   ```
3. Run: `py scripts/ragas_baseline.py --test-set C:/tmp/ragas_test_set.json`
4. Results saved to: `C:/tmp/ragas_baseline.json`

**Pre-downloaded sample datasets** (50 Q&A pairs each, no job_id yet):
- `Data set/ragas_eval/ms_marco_samples.json` — MS MARCO v1.1 validation
- `Data set/ragas_eval/natural_questions_samples.json` — Natural Questions dev

To use these, upload relevant documents first, then add the returned `job_id` to the JSON entries.

---

## Frontend Pages

| URL | Page | What it does |
|---|---|---|
| `/login` | LoginPage | Email/password login, stores JWT |
| `/register` | RegisterPage | New user registration |
| `/upload` | UploadPage | Drag-drop upload, job polling, summary drawer |
| `/query` | QueryPage | Select docs, ask question, streaming mode, citation links |
| `/agent` | AgentPage | Chat with ADK agent, tool call log sidebar |
| `/jobs` | JobsPage | Full jobs table, re-process button |
| `/admin` | AdminPage | Usage/RAGAS/user management tabs (admin only) |

**All pages lazy-loaded** (React.lazy + Suspense) — main bundle ~211KB after code splitting.

---

## Key Design Decisions (for context)

1. **`google-genai` not `google-generativeai`** — The old SDK (`google-generativeai`) is deprecated. Always use `google-genai>=1.0.0` with `from google import genai`.

2. **SSE streaming uses Fetch not EventSource** — EventSource API doesn't support POST requests or custom headers. The frontend uses `fetch()` with `ReadableStream` reader to stream answers with auth.

3. **ChromaDB 3x retry** — `add_chunks()` retries 3 times with 5s backoff because ChromaDB can have transient write failures.

4. **RAGAS is async** — Computing RAGAS after every query adds 15-60s latency. It runs in a background Celery task (`compute_ragas`). The query response returns immediately; RAGAS scores appear in QueryHistory later.

5. **ALLOWED_ORIGINS is env-driven** — Set `ALLOWED_ORIGINS=https://your-domain.com` in .env for production. In dev it defaults to `http://localhost:5173`.

6. **No Docker** — All infrastructure runs natively on this machine. PostgreSQL (v18), Redis, ChromaDB are already running as system services.

7. **Windows Celery** — Must use `--pool=solo` flag. Celery's default prefork pool doesn't work on Windows.

---

## Known Limitations

1. **Speaker diarization accuracy** — depends on audio quality. Mono recordings work best.
2. **Large video files** — >500 MB rejected. Close-to-limit files may hit Gemini context window.
3. **RAGAS cost** — ~15-60s and token cost per query. Disable by removing `compute_ragas.delay()` from `app/rag/engine.py`.
4. **In-memory agent sessions** — ADK InMemorySessionService resets on server restart.
5. **ChromaDB not backed up** — Lives in Docker named volume. If deleted, re-upload all documents.
6. **No email notifications** — No notification when long jobs complete. Planned future feature.

---

## Adding a New File Type

1. Create `app/processors/newtype.py` extending `BaseProcessor` — implement `extract()` and `summarise()`
2. Add extension to `EXTENSION_MAP` in `app/api/files.py`
3. Add extension to `EXT_TO_TYPE` in `frontend/src/pages/UploadPage.tsx`
4. Add dispatch case in `process_file()` in `app/workers/tasks.py`
5. Write a test in `tests/test_processors.py`

---

## Git History (recent)

```
5965edb feat: day 8-10 + buffer — frontend, security hardening, streaming, delivery docs
636fd39 fix: phase-1 checklist gaps — otel spans, from_status logging, user_id in http middleware
48f3cfa day-7: ragas evaluation, observability audit, baseline
39c873f day-6: rag engine, citations, confidence gate, admin api
a8fbf32 day-4: image and video/audio processors, diarization, 14 tests pass
3f24a13 day-3: migrate to google.genai SDK, verify processors end-to-end
```

---

## Project Directory

```
playbook_final/
└── geminirag/               ← main project root
    ├── app/                 ← FastAPI backend
    │   ├── main.py
    │   ├── config.py
    │   ├── deps.py
    │   ├── security.py
    │   ├── limiter.py
    │   ├── api/             ← route handlers
    │   ├── models/          ← SQLModel ORM
    │   ├── processors/      ← file type processors
    │   ├── rag/             ← chunker, embedder, vectorstore, engine
    │   ├── workers/         ← Celery tasks
    │   ├── agent/           ← ADK agent + tools
    │   ├── evaluation/      ← RAGAS eval
    │   └── observability/   ← logging + tracing
    ├── frontend/            ← React + TypeScript
    │   └── src/
    │       ├── pages/       ← 7 pages
    │       ├── context/     ← Auth + Toast contexts
    │       ├── components/  ← NavBar, PrivateRoute
    │       ├── hooks/       ← useToast
    │       └── api/         ← Axios client
    ├── scripts/             ← seed_admin, ragas_baseline, download_datasets
    ├── tests/               ← pytest test suite
    ├── migrations/          ← Alembic migration files
    ├── Data set/            ← test datasets
    │   └── ragas_eval/      ← ms_marco_samples.json, natural_questions_samples.json
    ├── .env                 ← secrets (gitignored)
    ├── .env.example         ← template
    ├── pyproject.toml       ← Python deps
    ├── docker-compose.yml   ← dev (not used locally)
    ├── docker-compose.prod.yml
    ├── Dockerfile
    ├── alembic.ini
    ├── README.md
    ├── HANDOVER.md
    └── DEMO_SCRIPT.md
```

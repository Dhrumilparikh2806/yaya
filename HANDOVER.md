# GeminiRAG — Handover Document
**Project:** GeminiRAG — Multimodal RAG Pipeline  
**Delivered by:** Dhrumil Parikh  
**Delivery date:** 3 June 2026  
**Client:** MasterCRM Internal Engineering

---

## How to Run the System

### 1. Prerequisites
- Docker Desktop running
- Python 3.11+
- Node.js 18+
- A valid Gemini API key from [aistudio.google.com](https://aistudio.google.com)

### 2. First-time Setup

```bash
git clone <repo-url>
cd geminirag

# Copy and fill in environment variables
cp .env.example .env
# Edit .env:
#   GEMINI_API_KEY=<your real key>
#   SECRET_KEY=<32+ random chars>

# Start infrastructure
docker compose up -d postgres redis chromadb

# Install Python dependencies
pip install -e .

# Run database migrations
alembic upgrade head

# Create the first admin user
python scripts/seed_admin.py --email admin@mastercrm.com --password YourSecurePassword123!

# Start the API server
uvicorn app.main:app --reload --port 8000

# Start the Celery worker (new terminal)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

### 3. Start the Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

### 4. Production (Docker only)

```bash
docker compose -f docker-compose.prod.yml up --build
# Set ALLOWED_ORIGINS=https://your-domain.com in .env before running
```

---

## Admin Credentials for Demo

Create them using the seed script:

```bash
python scripts/seed_admin.py --email demo@mastercrm.com --password Demo2026!
```

To reset: delete the user row in PostgreSQL and re-run.

---

## RAGAS Baseline Scores

Run after uploading test documents and creating Q&A pairs:

```bash
# Create test set at /tmp/ragas_test_set.json:
# [{"question": "...", "ground_truth": "...", "job_id": "..."}]

python scripts/ragas_baseline.py --test-set /tmp/ragas_test_set.json
# Results: /tmp/ragas_baseline.json
```

**Target scores (from BUILD.md spec):**
- Faithfulness ≥ 0.80
- Context Precision ≥ 0.60

---

## Known Limitations

1. **Speaker diarization accuracy** depends on audio quality. Mono recordings with minimal background noise work best. Multi-speaker files with similar voices may produce merged speaker labels.

2. **Large video files** (>500 MB) are rejected. Files close to the limit may hit Gemini's context window for frame extraction.

3. **RAGAS adds ~15–60s and token cost** per query (async background task). This can be significant at high volume. To disable: remove `compute_ragas.delay(str(qh.id))` from `app/rag/engine.py`.

4. **In-memory agent sessions** — ADK uses `InMemorySessionService`. Agent conversation history resets on server restart. For production, replace with a persistent session service backed by Redis or PostgreSQL.

5. **ChromaDB embeddings are not backed up** — they live in a Docker named volume. If the volume is deleted, all documents must be re-uploaded and re-processed. Back up the `chromadata` volume before any infrastructure changes.

6. **No email notifications** — the system does not email users when long-running jobs complete. This is a planned future enhancement.

---

## How to Add a New File Type

1. Create `app/processors/newtype.py` extending `BaseProcessor` — implement `extract()` returning `(text, summary_dict)`
2. Add the file extension to `EXTENSION_MAP` in `app/api/files.py`
3. Add the extension to `EXT_TO_TYPE` in `frontend/src/pages/UploadPage.tsx`
4. Add the dispatch case to `process_file()` in `app/workers/tasks.py`
5. Write a test in `tests/test_processors.py`

---

## Architecture Summary

```
React Frontend (port 5173)
    ↓ HTTP + JWT
FastAPI (port 8000)
    ↓ Celery tasks
Redis (port 6379) → Celery Worker
    ↓ Results + metadata
PostgreSQL (port 5432)
    ↓ Embeddings
ChromaDB (port 8001)
    ↓ All AI calls
Gemini API (google-genai)
```

---

## Key Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app factory, CORS, request logging |
| `app/config.py` | All env vars, startup validation |
| `app/api/` | All route handlers |
| `app/processors/base.py` | Gemini call wrapper, error classification |
| `app/rag/engine.py` | RAG query + confidence gate |
| `app/agent/agent.py` | ADK agent runner |
| `app/agent/tools.py` | 5 MCP tools |
| `app/workers/tasks.py` | Celery task pipeline |
| `scripts/seed_admin.py` | Create initial admin |
| `scripts/ragas_baseline.py` | Offline RAGAS evaluation |

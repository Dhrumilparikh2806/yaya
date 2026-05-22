# GeminiRAG — Demo Script
## Client Presentation Guide

**Total time: ~10 minutes**
**Prerequisites:** Backend running on :8000, frontend on :5173, at least one PDF uploaded, one audio file ready

---

## 1. Architecture Walkthrough (2 min)

**Say:**
> "GeminiRAG is a multimodal document intelligence platform. Let me walk through what's happening under the hood."

Point to the terminal (structlog output) and explain each layer:

- **FastAPI** handles all REST calls. Every request is logged as structured JSON with a `request_id`, `user_id`, and `latency_ms`.
- **Celery + Redis** queue file processing jobs so uploads return immediately — heavy Gemini work happens in the background.
- **Gemini 2.0 Flash** does all the heavy lifting: extracting text from PDFs, transcribing audio, diarizing speakers, OCR on images.
- **ChromaDB** stores the vector embeddings for semantic search.
- **PostgreSQL** stores jobs, users, query history, and per-user token spend.
- **Google ADK agent** can chain multiple tools in one conversation turn — upload, poll status, and summarize from a single message.

**Say:**
> "Everything that Gemini touches is logged with token counts and latency. The admin dashboard shows this in real time."

---

## 2. File Ingestion Demo (3 min)

### 2a. PDF upload

1. Open **Upload** page in the browser.
2. Drag in `attention.pdf` (or any PDF).
3. Point to the status badge: **PENDING → PROCESSING**.
4. Switch to terminal — show the structlog output:
   ```
   {"event": "file_uploaded", "filename": "attention.pdf", ...}
   {"event": "job_state_change", "status": "PROCESSING", "step": "extracting_text", ...}
   {"event": "gemini_call", "model": "gemini-2.0-flash", "prompt_tokens": 1240, ...}
   {"event": "job_state_change", "status": "COMPLETED", ...}
   ```
5. Badge turns **COMPLETED** (green). Click **View Summary** — show key points, title, and summary in the slide drawer.

**Say:**
> "Every step from upload through ChromaDB indexing is fully traceable by job ID in the logs."

### 2b. Audio transcript (if file available)

1. Upload a `.mp3` meeting recording.
2. Once COMPLETED, open the summary drawer.
3. Show the diarized segments: **Speaker 1**, **Speaker 2**, timestamps, action items, key decisions.

**Say:**
> "Speaker diarization uses Gemini's multimodal understanding — no separate diarization service needed."

---

## 3. RAG Query Demo (2 min)

1. Open **Query** page.
2. Leave all documents selected (or select just the PDF you uploaded).

### Factual question

Type: *"What is the main contribution of the paper?"*

- Point to the answer with **[1][2]** citation superscripts.
- Click **[1]** — page scrolls to the citation block showing filename, page/segment, and excerpt.
- Wait for RAGAS badges to appear (10–60 seconds): green = good, amber = acceptable, red = needs attention.

**Say:**
> "Every answer includes citations back to the source chunk. RAGAS metrics are computed automatically in the background — faithfulness tells us the answer is grounded, answer relevancy tells us it actually addressed the question."

### Nonsense/out-of-scope question

Type: *"What is the capital of Mars?"*

- Show the amber **"Low confidence"** box.
- No hallucinated citations — the confidence gate blocked a fabricated answer.

**Say:**
> "The confidence gate prevents hallucination when the retrieved context doesn't actually contain an answer."

---

## 4. Admin Dashboard Demo (2 min)

1. Log in as an admin user.
2. Open **/admin**.

### Usage tab

- Show the **3 summary cards**: tokens today, total calls, avg latency.
- Point to the **line chart** showing token volume over the past 7 days.
- Show the **Endpoints table** — which routes are most expensive.
- Show the **Per user table** — who is spending the most tokens.

### RAGAS tab

- Show the **5 metric cards** (faithfulness, relevancy, precision, recall, correctness).
- Point to the **7-day trend chart** — are scores stable?
- Show the **Low-scoring queries table** — these are candidates for prompt improvement.

### Users tab

- Show both test users.
- Demonstrate the **toggle active** button (note: you can't deactivate yourself).

**Say:**
> "The admin dashboard gives a complete picture of system health — cost, quality, and user behaviour in one place."

---

## 5. Agent Demo (1 min)

1. Open **Agent Chat** page.
2. Type: *"List all my uploaded documents"*
   - Show the **tool log panel** on the left lighting up with `list_documents`.
3. Type: *"What did the PDF say about attention mechanisms?"*
   - Show `query_rag` appearing in the tool log.
   - Point to the token footer on the agent response.

**Say:**
> "The ADK agent decides which tools to call based on the question — you don't have to specify. It can also chain tools: one message like 'ingest this file and summarise it' will call ingest, poll until complete, then call summarize."

---

## Things to Say If Something Goes Wrong

| Problem | What to say | What to do |
|---|---|---|
| File stuck at PROCESSING | "The Celery worker is processing — let me check the logs." | `docker compose logs worker --tail 20` |
| RAGAS badges not appearing | "RAGAS evaluation runs async — it takes 30–60 seconds and calls Gemini again." | Wait, or refresh the query |
| Agent returns an error | "The agent hit a rate limit — Gemini throttles at high volume." | Wait 30s, resend |
| 401 on API calls | "JWT expired — let me log in again." | Log out and back in |
| ChromaDB returns no results | "The document may still be indexing." | Check job status is COMPLETED |
| Admin chart shows no data | "The usage chart shows data from actual queries — it populates after the first query." | Run a query, refresh admin |
| Gemini 429 error in logs | "Gemini free tier has rate limits — the worker will retry automatically." | Wait 60s for auto-retry |

---

## Key Numbers to Mention

- Upload to COMPLETED: **~10–30 seconds** for a typical PDF
- RAG query latency: **~1–3 seconds** end-to-end
- RAGAS evaluation: **~15–60 seconds** async (doesn't block the answer)
- Supported file types: **PDF, DOCX, XLSX, CSV, PNG, JPG, MP4, MOV, MP3, WAV, M4A**
- Max file size: **500 MB**

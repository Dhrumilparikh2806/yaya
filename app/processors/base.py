"""
Abstract base class for all file processors.

Subclasses implement two methods:
  extract()   — parse the raw file into a markdown string (no LLM call).
  summarise() — call the LLM and return a structured summary dict.

The base class provides:
  run()                  — orchestrates extract → summarise, pops internal
                           keys (_chunk_text, _speaker_embeddings) before
                           persisting the summary to Job.result, then returns
                           (chunk_text, summary) to the Celery task.
  _call_gemini_json()    — Groq text LLM → parsed JSON dict (name is legacy;
                           uses GROQ_PROCESSING_MODEL).
  _call_vision_markdown()— Groq Vision LLM → plain markdown string.
  _call_gemini_vision_json() — Groq Vision LLM → parsed JSON dict.
  _table_to_markdown()   — converts a list-of-rows table to a markdown table.

Every LLM method retries up to 4 times with 30 s × attempt back-off on
RateLimitError and 503 / 413 errors, and raises InvalidInputError immediately
on 400 BadRequest.
"""

import base64
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

import groq as groq_sdk

from app.observability.logging import get_logger, log_llm_call


class RateLimitError(Exception):
    pass


class InvalidInputError(Exception):
    pass


class BaseProcessor(ABC):
    def __init__(self, job, settings):
        self.job = job
        self.settings = settings
        self.log = get_logger().bind(job_id=str(job.id), file_type=job.file_type)
        self._client = groq_sdk.Groq(api_key=settings.GROQ_API_KEY)

    @abstractmethod
    def extract(self) -> str:
        """Extract raw markdown from the file. Returns markdown string."""

    @abstractmethod
    def summarise(self, text: str, db) -> dict:
        """Call LLM and return structured summary dict.
        May include '_chunk_text' key to override what gets chunked."""

    def run(self, db) -> tuple[str, dict]:
        """Called by Celery task. Returns (markdown_for_chunking, summary_dict)."""
        text = self.extract()
        summary = self.summarise(text, db)
        # Allow processors to override chunking text via '_chunk_text' key
        chunk_override = summary.pop("_chunk_text", None)
        # Strip large internal keys before persisting to DB, then restore for the caller.
        speaker_embeddings = summary.pop("_speaker_embeddings", None)
        self.job.result = json.dumps(summary)
        db.add(self.job)
        db.commit()
        if speaker_embeddings is not None:
            summary["_speaker_embeddings"] = speaker_embeddings

        chunk_text = chunk_override if chunk_override is not None else text

        # Save markdown to disk alongside the source file
        if chunk_text.strip():
            md_path = Path(self.job.file_path).parent / "extracted.md"
            try:
                md_path.write_text(chunk_text, encoding="utf-8")
                self.log.info("markdown_saved", path=str(md_path), chars=len(chunk_text))
            except Exception as exc:
                self.log.warning("markdown_save_failed", error=str(exc))

        return chunk_text, summary

    def _call_gemini_json(self, prompt: str, db) -> dict:
        """LLM text call — returns parsed JSON dict."""
        start = time.time()
        for attempt in range(4):
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.GROQ_PROCESSING_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=512,
                )
                break
            except groq_sdk.RateLimitError as e:
                if attempt < 3:
                    wait = 30 * (attempt + 1)
                    self.log.warning("groq_rate_limit_retry", attempt=attempt, wait_s=wait)
                    time.sleep(wait)
                    continue
                raise RateLimitError(f"429: Groq rate limit — {e}") from e
            except groq_sdk.BadRequestError as e:
                raise InvalidInputError(f"400: Groq invalid argument — {e}") from e
            except groq_sdk.APIStatusError as e:
                if e.status_code in (413, 503):
                    if attempt < 3:
                        time.sleep(30 * (attempt + 1))
                        continue
                    raise RateLimitError(f"{e.status_code}: Groq unavailable — {e}") from e
                raise

        latency_ms = int((time.time() - start) * 1000)
        text = response.choices[0].message.content

        log_llm_call(
            user_id=self.job.user_id,
            job_id=self.job.id,
            endpoint=f"{self.job.file_type}_processor",
            model=self.settings.GROQ_PROCESSING_MODEL,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=text[:500],
            db=db,
        )

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            self.log.error("groq_json_parse_failed", raw=text[:1000])
            raise ValueError(f"Groq response was not valid JSON: {e}") from e

    def _call_vision_markdown(self, prompt: str, image_data: bytes, mime_type: str, db) -> str:
        """Vision LLM call — returns plain markdown text."""
        start = time.time()
        b64_image = base64.b64encode(image_data).decode("utf-8")
        for attempt in range(4):
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.GROQ_VISION_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    max_tokens=2048,
                )
                break
            except groq_sdk.RateLimitError as e:
                if attempt < 3:
                    wait = 30 * (attempt + 1)
                    self.log.warning("groq_vision_rate_limit_retry", attempt=attempt, wait_s=wait)
                    time.sleep(wait)
                    continue
                raise RateLimitError(f"429: Groq rate limit — {e}") from e
            except groq_sdk.BadRequestError as e:
                raise InvalidInputError(f"400: Groq invalid argument — {e}") from e
            except groq_sdk.APIStatusError as e:
                if e.status_code == 503:
                    if attempt < 3:
                        time.sleep(30 * (attempt + 1))
                        continue
                    raise RateLimitError(f"503: Groq unavailable — {e}") from e
                raise

        latency_ms = int((time.time() - start) * 1000)
        text = response.choices[0].message.content or ""

        log_llm_call(
            user_id=self.job.user_id,
            job_id=self.job.id,
            endpoint="image_processor",
            model=self.settings.GROQ_VISION_MODEL,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=text[:500],
            db=db,
        )

        return text

    def _call_gemini_vision_json(self, prompt: str, image_data: bytes, mime_type: str, db) -> dict:
        """Vision LLM call — returns parsed JSON dict."""
        start = time.time()
        b64_image = base64.b64encode(image_data).decode("utf-8")
        try:
            response = self._client.chat.completions.create(
                model=self.settings.GROQ_VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                response_format={"type": "json_object"},
                max_tokens=512,
            )
        except groq_sdk.RateLimitError as e:
            raise RateLimitError(f"429: Groq rate limit — {e}") from e
        except groq_sdk.BadRequestError as e:
            raise InvalidInputError(f"400: Groq invalid argument — {e}") from e
        except groq_sdk.APIStatusError as e:
            if e.status_code == 503:
                raise RateLimitError(f"503: Groq unavailable — {e}") from e
            raise

        latency_ms = int((time.time() - start) * 1000)
        text = response.choices[0].message.content

        log_llm_call(
            user_id=self.job.user_id,
            job_id=self.job.id,
            endpoint="image_processor",
            model=self.settings.GROQ_VISION_MODEL,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=text[:500],
            db=db,
        )

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            self.log.error("groq_vision_json_parse_failed", raw=text[:1000])
            raise ValueError(f"Groq vision response was not valid JSON: {e}") from e

    @staticmethod
    def _table_to_markdown(rows: list[list]) -> str:
        if not rows:
            return ""
        cleaned = [[str(cell) if cell is not None else "" for cell in row] for row in rows]
        if not cleaned:
            return ""
        header = "| " + " | ".join(cleaned[0]) + " |"
        separator = "| " + " | ".join(["---"] * len(cleaned[0])) + " |"
        body_rows = ["| " + " | ".join(row) + " |" for row in cleaned[1:]]
        return "\n".join([header, separator] + body_rows)

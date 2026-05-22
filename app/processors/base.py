import json
import time
from abc import ABC, abstractmethod
from typing import Any

from google import genai
from google.genai import errors as genai_errors, types as genai_types

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
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    @abstractmethod
    def extract(self) -> str:
        """Extract raw text from the file. Returns plain text string."""

    @abstractmethod
    def summarise(self, text: str, db) -> dict:
        """Call Gemini and return structured summary dict."""

    def run(self, db) -> tuple[str, dict]:
        """Called by Celery task. Returns (extracted_text, summary_dict)."""
        text = self.extract()
        summary = self.summarise(text, db)
        self.job.result = json.dumps(summary)
        db.add(self.job)
        db.commit()
        return text, summary

    def _call_gemini_json(self, prompt: str, db) -> dict:
        start = time.time()
        try:
            response = self._client.models.generate_content(
                model=self.settings.GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
        except genai_errors.ClientError as e:
            if e.code == 429:
                raise RateLimitError(f"429: Gemini rate limit — {e}") from e
            if e.code == 400:
                raise InvalidInputError(f"400: Gemini invalid argument — {e}") from e
            raise
        except genai_errors.ServerError as e:
            raise RateLimitError(f"503: Gemini unavailable — {e}") from e

        latency_ms = int((time.time() - start) * 1000)

        log_llm_call(
            user_id=self.job.user_id,
            job_id=self.job.id,
            endpoint=f"{self.job.file_type}_processor",
            model=self.settings.GEMINI_MODEL,
            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
            completion_tokens=response.usage_metadata.candidates_token_count or 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=response.text[:500],
            db=db,
        )

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            self.log.error("gemini_json_parse_failed", raw=response.text[:1000])
            raise ValueError(f"Gemini response was not valid JSON: {e}") from e

    def _call_gemini_vision_json(self, prompt: str, image_data: bytes, mime_type: str, db) -> dict:
        start = time.time()
        try:
            response = self._client.models.generate_content(
                model=self.settings.GEMINI_MODEL,
                contents=[
                    genai_types.Part.from_bytes(data=image_data, mime_type=mime_type),
                    prompt,
                ],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
        except genai_errors.ClientError as e:
            if e.code == 429:
                raise RateLimitError(f"429: Gemini rate limit — {e}") from e
            if e.code == 400:
                raise InvalidInputError(f"400: Gemini invalid argument — {e}") from e
            raise
        except genai_errors.ServerError as e:
            raise RateLimitError(f"503: Gemini unavailable — {e}") from e

        latency_ms = int((time.time() - start) * 1000)

        log_llm_call(
            user_id=self.job.user_id,
            job_id=self.job.id,
            endpoint="image_processor",
            model=self.settings.GEMINI_MODEL,
            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
            completion_tokens=response.usage_metadata.candidates_token_count or 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=response.text[:500],
            db=db,
        )

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            self.log.error("gemini_vision_json_parse_failed", raw=response.text[:1000])
            raise ValueError(f"Gemini vision response was not valid JSON: {e}") from e

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

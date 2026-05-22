import os
import time

from google.genai import errors as genai_errors, types as genai_types

from app.observability.logging import log_llm_call
from app.processors.base import BaseProcessor, RateLimitError, InvalidInputError

DIARIZATION_PROMPT = """You are an expert transcription service. Transcribe this recording exactly.

Rules:
- Identify each distinct speaker. Label them "Speaker 1", "Speaker 2", etc.
- Use the SAME label for the SAME speaker throughout — never switch labels for one person.
- Include timestamps in MM:SS format for each segment.
- Transcribe every word spoken. Do not summarise or paraphrase.

Return ONLY valid JSON with this exact structure. No preamble, no markdown.

{
  "duration_seconds": 0,
  "speaker_count": 0,
  "speakers": ["Speaker 1", "Speaker 2"],
  "segments": [
    {
      "speaker": "Speaker 1",
      "timestamp": "00:00",
      "text": "exact words spoken"
    }
  ],
  "full_transcript": "continuous transcript with speaker labels inline: Speaker 1: ... Speaker 2: ...",
  "summary": "2-3 sentence summary of the meeting/recording",
  "action_items": ["action item 1", "action item 2"],
  "key_decisions": ["decision 1", "decision 2"],
  "topics_discussed": ["topic 1", "topic 2"]
}
"""


class VideoAudioProcessor(BaseProcessor):
    def extract(self) -> str:
        file_size = os.path.getsize(self.job.file_path)
        self.log.info("uploading_to_gemini_files", file_size=file_size)

        start = time.time()
        uploaded_file = self._client.files.upload(
            file=self.job.file_path,
            config=genai_types.UploadFileConfig(display_name=self.job.filename),
        )

        timeout = 300  # 5 minutes
        last_log = start
        while str(uploaded_file.state) in ("FileState.PROCESSING", "PROCESSING"):
            elapsed = time.time() - start
            if elapsed > timeout:
                raise ValueError(f"Upload timeout after {timeout}s for {self.job.filename}")
            if time.time() - last_log >= 30:
                self.log.info("gemini_upload_in_progress", elapsed_s=int(elapsed))
                last_log = time.time()
            time.sleep(2)
            uploaded_file = self._client.files.get(name=uploaded_file.name)

        state_str = str(uploaded_file.state)
        if "FAILED" in state_str:
            raise ValueError(f"Gemini file upload failed: {state_str}")

        self.log.info(
            "gemini_upload_complete",
            upload_s=int(time.time() - start),
            file_size=file_size,
        )
        self._uploaded_file = uploaded_file
        return ""

    def summarise(self, text: str, db) -> dict:
        import json

        start = time.time()
        try:
            response = self._client.models.generate_content(
                model=self.settings.GEMINI_MODEL,
                contents=[self._uploaded_file, DIARIZATION_PROMPT],
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
            endpoint="video_audio_processor",
            model=self.settings.GEMINI_MODEL,
            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
            completion_tokens=response.usage_metadata.candidates_token_count or 0,
            latency_ms=latency_ms,
            query_text=self.job.filename,
            llm_response_preview=response.text[:500],
            db=db,
        )

        try:
            result = json.loads(response.text)
        except json.JSONDecodeError as e:
            self.log.error("video_json_parse_failed", raw=response.text[:1000])
            raise ValueError(f"Gemini diarization response was not valid JSON: {e}") from e

        if "segments" not in result or not isinstance(result["segments"], list):
            raise ValueError(
                f"Diarization response missing 'segments' list: {list(result.keys())}"
            )

        return result

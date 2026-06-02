"""
Audio file processor (MP3, WAV, M4A, AAC, FLAC, OGG, WEBM).

Pipeline:
  1. Groq Whisper transcription — produces timestamped segments with
     language detection.  Files larger than MAX_AUDIO_CHUNK_MB are split
     into overlapping chunks by pydub before sending to the API.
  2. SpeechBrain ECAPA-VOXCELEB diarization — clusters 1.5-second audio
     windows into speakers via AgglomerativeClustering.  The ECAPA model
     is lazy-loaded and globally cached (_ecapa_model in audio_utils).
     Returns both speaker segments and per-speaker mean ECAPA embeddings.
  3. Merge — Whisper segments are labelled with the dominant diarization
     speaker for each time range.
  4. Markdown — segments formatted as '## [Speaker N at MM:SS]' blocks.
  5. Groq LLM summary — summary, action_items, key_decisions, topics.

The speaker ECAPA embeddings (192-dim float lists) are passed through
summary['_speaker_embeddings'] so tasks.py can tag each ChromaDB chunk
with the embedding for its speaker.
"""

from app.processors.base import BaseProcessor
from app.processors.audio_utils import (
    transcribe_audio,
    diarize_audio,
    merge_transcript_diarization,
    segments_to_markdown,
    summarise_transcript,
)

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}


class AudioProcessor(BaseProcessor):
    """
    Processes audio files through the full pipeline:
      1. Groq Whisper transcription (with large-file splitting)
      2. SpeechBrain ECAPA speaker diarization
      3. Merge → speaker-labelled markdown
      4. Groq LLM summary (action items, decisions, topics)
    """

    def extract(self) -> str:
        # All work requires the DB connection for logging, so it happens in summarise.
        return ""

    def summarise(self, text: str, db) -> dict:
        self.log.info("audio_processor_start", filename=self.job.filename)

        # 1. Transcribe via Groq Whisper
        whisper_segs, detected_lang, duration_s = transcribe_audio(
            self._client, self.job.file_path, self.settings, self.log, db, self.job
        )
        self.log.info("whisper_transcription_done",
                      segment_count=len(whisper_segs),
                      language=detected_lang,
                      duration_s=round(duration_s, 1))

        # 2. Diarize via SpeechBrain ECAPA — also retrieve per-speaker ECAPA embeddings
        speaker_segs, speaker_embeddings = diarize_audio(
            self.job.file_path, self.log, self.settings.DIARIZATION_THRESHOLD,
            return_embeddings=True,
        )
        self.log.info("diarization_done", speaker_segment_count=len(speaker_segs))

        # 3. Merge Whisper segments with speaker labels
        merged = merge_transcript_diarization(whisper_segs, speaker_segs)

        # 4. Build markdown for chunking
        md = segments_to_markdown(self.job.filename, merged)

        # 5. LLM summary
        summary = summarise_transcript(
            self._client, merged, self.job.filename, self.settings, self.log, db, self.job,
            language=detected_lang, duration_seconds=duration_s,
        )

        summary["_chunk_text"] = md
        # Pass ECAPA speaker embeddings through to tasks.py for chunk metadata tagging.
        # base.py strips this key before DB serialization so the large vectors are never stored.
        summary["_speaker_embeddings"] = speaker_embeddings
        self.log.info(
            "audio_processor_done",
            speaker_count=summary.get("speaker_count"),
            duration_seconds=summary.get("duration_seconds"),
            md_chars=len(md),
        )
        return summary

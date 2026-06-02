"""
Shared audio transcription and speaker diarization utilities.

Transcription  : Groq Whisper (whisper-large-v3), verbose_json with segment timestamps.
Diarization    : SpeechBrain ECAPA-VOXCELEB embeddings + scikit-learn AgglomerativeClustering.
Large files    : pydub splits audio > MAX_AUDIO_CHUNK_MB into overlapping chunks.
"""

import json
import os
import tempfile
import time
from pathlib import Path

import groq as groq_sdk
import numpy as np

# Configure pydub to use imageio-ffmpeg's bundled binary when system ffmpeg isn't on PATH.
# imageio-ffmpeg ships a static ffmpeg binary, so this works on any platform without
# requiring a separate ffmpeg installation.
try:
    from imageio_ffmpeg import get_ffmpeg_exe as _get_ffmpeg_exe
    from pydub import AudioSegment as _AS
    _AS.converter = _get_ffmpeg_exe()
except Exception:
    pass

from app.observability.logging import log_llm_call
from app.processors.base import InvalidInputError, RateLimitError

# ── MIME types accepted by Groq Whisper ───────────────────────────────────────
_AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
}

# ── Lazy-loaded global ECAPA model (same pattern as reranker) ─────────────────
_ecapa_model = None


def _get_ecapa_model():
    global _ecapa_model
    if _ecapa_model is None:
        # SpeechBrain 1.0+ moved to speechbrain.inference; keep fallback for older versions
        try:
            from speechbrain.inference.classifiers import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier  # type: ignore[no-redef]

        # No custom savedir — let SpeechBrain use its default local cache to avoid
        # Windows symlink privilege errors (WinError 1314) that occur when copying
        # model files to a separate directory.
        import os
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        _ecapa_model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
    return _ecapa_model


# ── Large file splitting ───────────────────────────────────────────────────────

def _split_large_audio(file_path: str, max_mb: int, log) -> list[tuple[str, float]]:
    """
    Split audio file into chunks of at most max_mb MB with a 10-second overlap.
    Returns list of (temp_wav_path, offset_seconds).
    The caller is responsible for deleting temp files.
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(file_path)
    total_ms = len(audio)

    # Bytes per ms ≈ sample_rate * channels * (bit_depth/8) / 1000
    bytes_per_ms = audio.frame_rate * audio.channels * (audio.sample_width) / 1000
    chunk_ms = int((max_mb * 1024 * 1024) / bytes_per_ms)
    overlap_ms = 10_000  # 10-second overlap

    chunks: list[tuple[str, float]] = []
    start_ms = 0
    while start_ms < total_ms:
        end_ms = min(start_ms + chunk_ms, total_ms)
        segment = audio[start_ms:end_ms]

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        segment.export(tmp.name, format="wav")
        chunks.append((tmp.name, start_ms / 1000.0))

        if end_ms >= total_ms:
            break
        start_ms += chunk_ms - overlap_ms

    log.info("audio_split", chunk_count=len(chunks), total_ms=total_ms)
    return chunks


def _ensure_whisper_format(file_path: str, log) -> tuple[str, bool]:
    """
    Convert audio to mp3 if the extension isn't natively supported by Whisper.
    Returns (path_to_use, was_converted). Caller deletes temp if was_converted=True.
    """
    ext = Path(file_path).suffix.lower()
    if ext in _AUDIO_MIME:
        return file_path, False

    log.info("audio_converting_format", from_ext=ext, to="mp3")
    from pydub import AudioSegment
    audio = AudioSegment.from_file(file_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    audio.export(tmp.name, format="mp3")
    return tmp.name, True


# ── Transcription ─────────────────────────────────────────────────────────────

def _transcribe_single(
    client: groq_sdk.Groq,
    file_path: str,
    settings,
    log,
    db,
    job,
    offset_seconds: float = 0.0,
) -> tuple[list[dict], str, float]:
    """
    Transcribe one audio file (must be < 25 MB) with Groq Whisper.
    Returns (segments, detected_language, duration_seconds).
    segments: [{start, end, text}] with timestamps offset-adjusted.
    detected_language: e.g. "english", "hindi", "spanish" — from Whisper response.
    duration_seconds: actual audio duration from Whisper (more accurate than segment end times).
    """
    ext = Path(file_path).suffix.lower()
    mime_type = _AUDIO_MIME.get(ext, "audio/mpeg")
    filename = Path(file_path).name

    with open(file_path, "rb") as f:
        audio_bytes = f.read()

    # Build API kwargs — only pass language when explicitly set (empty = auto-detect)
    api_kwargs: dict = dict(
        file=(filename, audio_bytes, mime_type),
        model=settings.WHISPER_MODEL,
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )
    if getattr(settings, "WHISPER_LANGUAGE", ""):
        api_kwargs["language"] = settings.WHISPER_LANGUAGE

    start_t = time.time()
    for attempt in range(4):
        try:
            response = client.audio.transcriptions.create(**api_kwargs)
            break
        except groq_sdk.RateLimitError as e:
            if attempt < 3:
                wait = 30 * (attempt + 1)
                log.warning("whisper_rate_limit_retry", attempt=attempt, wait_s=wait)
                time.sleep(wait)
                continue
            raise RateLimitError(f"429: Groq Whisper rate limit — {e}") from e
        except groq_sdk.BadRequestError as e:
            raise InvalidInputError(f"400: Groq Whisper invalid input — {e}") from e
        except groq_sdk.APIStatusError as e:
            if e.status_code in (503, 413):
                if attempt < 3:
                    time.sleep(30 * (attempt + 1))
                    continue
                raise RateLimitError(f"{e.status_code}: Groq Whisper unavailable — {e}") from e
            raise

    latency_ms = int((time.time() - start_t) * 1000)
    full_text = getattr(response, "text", "") or ""
    word_count = len(full_text.split())
    detected_language = getattr(response, "language", "") or ""
    duration_seconds = float(getattr(response, "duration", 0.0) or 0.0) + offset_seconds

    log.info("whisper_transcription_result",
             language=detected_language, duration_s=round(duration_seconds, 1))

    log_llm_call(
        user_id=job.user_id,
        job_id=job.id,
        endpoint="whisper_transcription",
        model=settings.WHISPER_MODEL,
        prompt_tokens=0,
        completion_tokens=word_count,
        latency_ms=latency_ms,
        query_text=job.filename,
        llm_response_preview=full_text[:500],
        db=db,
    )

    raw_segments = getattr(response, "segments", None) or []

    # verbose_json segments have .start, .end, .text as attributes
    segments = []
    for seg in raw_segments:
        s_start = getattr(seg, "start", 0.0) + offset_seconds
        s_end = getattr(seg, "end", s_start) + offset_seconds
        text = (getattr(seg, "text", "") or "").strip()
        if text:
            segments.append({"start": s_start, "end": s_end, "text": text})

    # Fallback: if no segments returned, wrap full text as a single segment
    if not segments and full_text.strip():
        segments = [{"start": offset_seconds, "end": offset_seconds, "text": full_text.strip()}]

    return segments, detected_language, duration_seconds


def transcribe_audio(
    client: groq_sdk.Groq,
    file_path: str,
    settings,
    log,
    db,
    job,
) -> tuple[list[dict], str, float]:
    """
    Transcribe audio file, handling files > MAX_AUDIO_CHUNK_MB by splitting.
    Returns (segments, detected_language, duration_seconds).
    - segments: [{start, end, text}] with absolute timestamps
    - detected_language: e.g. "english", "hindi" — from first chunk's Whisper response
    - duration_seconds: total duration of the audio
    """
    converted_path, was_converted = _ensure_whisper_format(file_path, log)

    try:
        file_size_mb = os.path.getsize(converted_path) / (1024 * 1024)

        if file_size_mb <= settings.MAX_AUDIO_CHUNK_MB:
            return _transcribe_single(client, converted_path, settings, log, db, job)

        log.info("audio_large_file_split", size_mb=round(file_size_mb, 1))
        chunks = _split_large_audio(converted_path, settings.MAX_AUDIO_CHUNK_MB, log)
        all_segments: list[dict] = []
        detected_language = ""
        max_duration = 0.0
        temp_paths = [p for p, _ in chunks]

        try:
            for chunk_path, offset_s in chunks:
                segs, lang, dur = _transcribe_single(
                    client, chunk_path, settings, log, db, job,
                    offset_seconds=offset_s,
                )
                all_segments.extend(segs)
                if not detected_language and lang:
                    detected_language = lang
                if dur > max_duration:
                    max_duration = dur
        finally:
            for p in temp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

        deduped = _dedup_segments(all_segments)
        return deduped, detected_language, max_duration

    finally:
        if was_converted:
            try:
                os.unlink(converted_path)
            except OSError:
                pass


def _dedup_segments(segments: list[dict]) -> list[dict]:
    """Remove duplicate/overlapping segments produced by chunked transcription."""
    if not segments:
        return segments
    segments = sorted(segments, key=lambda s: s["start"])
    result = [segments[0]]
    for seg in segments[1:]:
        prev = result[-1]
        # Skip if start is within the previous segment's end (overlap region)
        if seg["start"] < prev["end"] - 1.0:
            continue
        result.append(seg)
    return result


# ── Speaker Diarization ───────────────────────────────────────────────────────

def diarize_audio(
    file_path: str,
    log,
    diarization_threshold: float = 0.4,
    return_embeddings: bool = False,
):
    """
    Run SpeechBrain ECAPA-VOXCELEB speaker diarization.

    Returns:
        If return_embeddings=False (default):
            list of (start_seconds, end_seconds, "Speaker N") sorted by start time.
        If return_embeddings=True:
            (segments, speaker_embeddings) where speaker_embeddings is a dict mapping
            "Speaker N" → mean ECAPA embedding (list[float]) computed over all audio
            windows assigned to that speaker.

    Falls back to [(0, duration, "Speaker 1")], {} on any failure so the pipeline
    continues even if diarization is unavailable.
    """
    try:
        import torchaudio
        import torch
        from sklearn.cluster import AgglomerativeClustering

        model = _get_ecapa_model()

        waveform, sample_rate = torchaudio.load(file_path)

        # Resample to 16kHz (ECAPA's expected sample rate)
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
            waveform = resampler(waveform)
            sample_rate = 16000

        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        duration_s = waveform.shape[1] / sample_rate

        # Sliding window: 1.5s window, 0.75s stride
        window_samples = int(1.5 * sample_rate)
        stride_samples = int(0.75 * sample_rate)
        total_samples = waveform.shape[1]

        window_starts = list(range(0, total_samples - window_samples + 1, stride_samples))
        if not window_starts:
            # Audio shorter than one window → single speaker, no meaningful embedding
            fallback_seg = [(0.0, duration_s, "Speaker 1")]
            if return_embeddings:
                return fallback_seg, {}
            return fallback_seg

        embeddings = []
        window_times = []

        with torch.no_grad():
            for start in window_starts:
                end = start + window_samples
                chunk = waveform[:, start:end]
                # ECAPA expects (batch, time) tensor
                emb = model.encode_batch(chunk)
                emb_np = emb.squeeze().cpu().numpy()
                embeddings.append(emb_np)
                window_times.append((start / sample_rate, end / sample_rate))

        embeddings_array = np.stack(embeddings)

        # L2-normalise for cosine distance
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        embeddings_norm = embeddings_array / norms

        # Cluster — if only 1 window, skip clustering
        if len(embeddings_norm) == 1:
            labels = [0]
        else:
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=diarization_threshold,
                metric="cosine",
                linkage="average",
            )
            labels = clustering.fit_predict(embeddings_norm)

        # Build raw speaker segments from window labels
        raw_segments: list[tuple[float, float, str]] = []
        for (w_start, w_end), label in zip(window_times, labels):
            raw_segments.append((w_start, w_end, f"Speaker {label + 1}"))

        # Merge consecutive same-speaker windows
        merged = _merge_speaker_segments(raw_segments)
        log.info("diarization_complete", speaker_count=len({s[2] for s in merged}))

        if not return_embeddings:
            return merged

        # Compute per-speaker mean ECAPA embedding over all windows assigned to that speaker.
        # These are the SpeechBrain speaker embeddings stored alongside each transcript chunk.
        labels_arr = np.array(labels)
        speaker_embs: dict[str, list[float]] = {}
        for lbl in set(int(l) for l in labels_arr):
            speaker_label = f"Speaker {lbl + 1}"
            mask = labels_arr == lbl
            mean_emb = embeddings_array[mask].mean(axis=0).tolist()
            speaker_embs[speaker_label] = mean_emb

        log.info("ecapa_speaker_embeddings_computed", speaker_count=len(speaker_embs))
        return merged, speaker_embs

    except Exception as exc:
        log.warning("diarization_failed_fallback", error=str(exc))
        # Fallback: try to get duration, mark everything Speaker 1
        try:
            import torchaudio
            info = torchaudio.info(file_path)
            duration_s = info.num_frames / info.sample_rate
        except Exception:
            duration_s = 0.0
        fallback = [(0.0, duration_s, "Speaker 1")]
        if return_embeddings:
            return fallback, {}
        return fallback


def _merge_speaker_segments(
    raw: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """Merge consecutive windows with the same speaker label into contiguous segments."""
    if not raw:
        return raw
    merged = []
    cur_start, cur_end, cur_speaker = raw[0]
    for seg_start, seg_end, speaker in raw[1:]:
        if speaker == cur_speaker:
            cur_end = seg_end
        else:
            merged.append((cur_start, cur_end, cur_speaker))
            cur_start, cur_end, cur_speaker = seg_start, seg_end, speaker
    merged.append((cur_start, cur_end, cur_speaker))
    return merged


# ── Merge Whisper + Diarization ───────────────────────────────────────────────

def merge_transcript_diarization(
    whisper_segments: list[dict],
    speaker_segments: list[tuple[float, float, str]],
) -> list[dict]:
    """
    Assign a speaker label to each Whisper segment by finding the diarization
    segment with the maximum overlap. Returns [{speaker, timestamp, start, end, text}].
    """
    def dominant_speaker(seg_start: float, seg_end: float) -> str:
        best_speaker = "Speaker 1"
        best_overlap = -1.0
        for sp_start, sp_end, sp_label in speaker_segments:
            overlap = min(seg_end, sp_end) - max(seg_start, sp_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = sp_label
        return best_speaker

    merged = []
    for seg in whisper_segments:
        start = seg["start"]
        end = seg["end"]
        minutes = int(start // 60)
        seconds = int(start % 60)
        merged.append({
            "speaker": dominant_speaker(start, end),
            "timestamp": f"{minutes:02d}:{seconds:02d}",
            "start": start,
            "end": end,
            "text": seg["text"],
        })
    return merged


# ── Markdown builder ──────────────────────────────────────────────────────────

def segments_to_markdown(filename: str, merged_segments: list[dict]) -> str:
    """
    Convert merged speaker segments to hierarchical markdown.
    Consecutive segments from the same speaker are combined under one heading.
    """
    if not merged_segments:
        return f"# {filename}\n\n*No transcribable content found.*"

    lines = [f"# {filename}", ""]
    current_speaker = None
    current_ts = None
    current_texts: list[str] = []

    def flush():
        if current_texts:
            lines.append(f"## [{current_speaker} at {current_ts}]")
            lines.append("")
            lines.append(" ".join(current_texts))
            lines.append("")

    for seg in merged_segments:
        if seg["speaker"] != current_speaker:
            flush()
            current_speaker = seg["speaker"]
            current_ts = seg["timestamp"]
            current_texts = [seg["text"]]
        else:
            current_texts.append(seg["text"])

    flush()
    return "\n".join(lines)


# ── LLM Summary ───────────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = """You are a meeting intelligence assistant. Given a transcript, extract structured metadata.
Return ONLY valid JSON with these keys:
{
  "summary": "2-3 sentence overview",
  "action_items": ["action 1", "action 2"],
  "key_decisions": ["decision 1"],
  "topics_discussed": ["topic 1", "topic 2"],
  "duration_seconds": 0,
  "speaker_count": 1,
  "speakers": ["Speaker 1"]
}
No preamble, no markdown fences."""


def summarise_transcript(
    client: groq_sdk.Groq,
    merged_segments: list[dict],
    filename: str,
    settings,
    log,
    db,
    job,
    language: str = "",
    duration_seconds: float = 0.0,
) -> dict:
    """
    Call Groq LLM to extract summary, action items, decisions, and topics from transcript.
    Returns a dict (without _chunk_text — caller adds that).
    language: detected language string from Whisper (e.g. "english", "hindi"). Empty = unknown.
    duration_seconds: accurate duration from Whisper response.
    """
    speakers = sorted({s["speaker"] for s in merged_segments}) if merged_segments else ["Speaker 1"]

    # Use Whisper's accurate duration; fall back to last segment end time
    if not duration_seconds and merged_segments:
        duration_seconds = merged_segments[-1]["end"]
    duration_s = int(duration_seconds)

    # Build compact transcript for the prompt (limit to ~3000 tokens worth)
    lang_hint = f"Language: {language}\n" if language else ""
    transcript_lines = [f"[{s['speaker']} at {s['timestamp']}] {s['text']}" for s in merged_segments]
    transcript_text = "\n".join(transcript_lines)
    if len(transcript_text) > 12000:
        transcript_text = transcript_text[:12000] + "\n...[truncated]"

    prompt = f"File: {filename}\n{lang_hint}Transcript:\n{transcript_text}"

    start_t = time.time()
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=settings.GROQ_PROCESSING_MODEL,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=1024,
            )
            break
        except groq_sdk.RateLimitError as e:
            if attempt < 3:
                wait = 30 * (attempt + 1)
                log.warning("transcript_summary_rate_limit", attempt=attempt, wait_s=wait)
                time.sleep(wait)
                continue
            raise RateLimitError(f"429: Groq rate limit — {e}") from e
        except groq_sdk.BadRequestError as e:
            raise InvalidInputError(f"400: Groq invalid request — {e}") from e
        except groq_sdk.APIStatusError as e:
            if e.status_code in (503, 413):
                if attempt < 3:
                    time.sleep(30 * (attempt + 1))
                    continue
                raise RateLimitError(f"{e.status_code}: Groq unavailable — {e}") from e
            raise

    latency_ms = int((time.time() - start_t) * 1000)
    text = response.choices[0].message.content or "{}"

    log_llm_call(
        user_id=job.user_id,
        job_id=job.id,
        endpoint="transcript_summary",
        model=settings.GROQ_PROCESSING_MODEL,
        prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
        completion_tokens=response.usage.completion_tokens if response.usage else 0,
        latency_ms=latency_ms,
        query_text=filename,
        llm_response_preview=text[:500],
        db=db,
    )

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("transcript_summary_json_failed", raw=text[:1000])
        result = {}

    # Fill in computed values, preferring LLM output but using our computed fallbacks
    result.setdefault("summary", f"Transcript of {filename}.")
    result.setdefault("action_items", [])
    result.setdefault("key_decisions", [])
    result.setdefault("topics_discussed", [])
    result.setdefault("duration_seconds", duration_s)
    result.setdefault("speaker_count", len(speakers))
    result.setdefault("speakers", speakers)
    result["language"] = language or "unknown"
    result["segments"] = [
        {"speaker": s["speaker"], "timestamp": s["timestamp"], "text": s["text"]}
        for s in merged_segments
    ]

    return result

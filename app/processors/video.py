"""
VideoProcessor — processes video files through two parallel tracks:

  AUDIO TRACK
    Extract audio → Groq Whisper transcription → SpeechBrain ECAPA diarization
    → speaker-labelled transcript markdown

  VISUAL TRACK
    Extract key frames every VIDEO_FRAME_INTERVAL seconds
    Skip near-duplicate frames (histogram comparison)
    Run Groq vision model on each distinct frame → visual description

  MERGE
    Interleave visual frame descriptions and transcript segments by timestamp
    → unified markdown → LLM summary
"""

import os
import shutil
import tempfile
from pathlib import Path

from app.processors.base import BaseProcessor, InvalidInputError
from app.processors.audio_utils import (
    transcribe_audio,
    diarize_audio,
    merge_transcript_diarization,
    summarise_transcript,
)
from app.processors.image import _EXTRACTION_PROMPT as _IMAGE_OCR_PROMPT

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v"}



class VideoProcessor(BaseProcessor):
    """
    Full video processing: audio transcription + speaker diarization + key frame vision analysis.
    """

    def __init__(self, job, settings):
        super().__init__(job, settings)
        self._audio_path: str | None = None          # temp .wav extracted from video
        self._audio_is_temp: bool = False            # whether we own the file
        self._frames: list[tuple[float, str]] = []   # (timestamp_s, jpeg_file_path)

    def extract(self) -> str:
        """Extract audio track and key frames from the video file."""
        self._extract_audio()
        self._extract_frames()
        return ""  # real work in summarise (needs db for logging)

    def summarise(self, text: str, db) -> dict:
        try:
            return self._build_summary(db)
        finally:
            self._cleanup_temp_audio()
            self._cleanup_frames()

    # ── Audio extraction ──────────────────────────────────────────────────────

    def _extract_audio(self) -> None:
        """Extract audio track from video to a temp WAV file using moviepy."""
        try:
            from moviepy import VideoFileClip
        except ImportError:
            raise InvalidInputError(
                "400: moviepy is required for video processing. Install with: pip install moviepy"
            )

        self.log.info("video_audio_extract_start", file=self.job.filename)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav",
            dir=str(Path(self.job.file_path).parent),
            delete=False,
        )
        tmp.close()
        self._audio_path = tmp.name
        self._audio_is_temp = True

        try:
            clip = VideoFileClip(self.job.file_path)
            if clip.audio is None:
                self.log.warning("video_no_audio_track", file=self.job.filename)
                clip.close()
                return
            clip.audio.write_audiofile(self._audio_path, logger=None)
            clip.close()
            size_mb = os.path.getsize(self._audio_path) / (1024 * 1024)
            self.log.info("video_audio_extract_done", size_mb=round(size_mb, 1))
        except Exception as exc:
            # Clean up the empty temp file before re-raising so it doesn't leak
            self._cleanup_temp_audio()
            self.log.error("video_audio_extract_failed", error=str(exc))
            raise InvalidInputError(f"400: Failed to extract audio from video — {exc}") from exc

    def _cleanup_temp_audio(self) -> None:
        if self._audio_is_temp and self._audio_path:
            try:
                os.unlink(self._audio_path)
            except OSError:
                pass

    def _cleanup_frames(self) -> None:
        frames_dir = Path(self.job.file_path).parent / "frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)

    # ── Frame extraction ──────────────────────────────────────────────────────

    def _extract_frames(self) -> None:
        """
        Extract one frame every VIDEO_FRAME_INTERVAL seconds.
        Skip near-duplicate frames using histogram comparison.
        Saves each kept frame as a JPEG file to disk and stores (timestamp_s, jpeg_path) in self._frames.
        """
        try:
            from moviepy import VideoFileClip
            import numpy as np
        except ImportError:
            self.log.warning("moviepy_not_available_skipping_frames")
            return

        interval = self.settings.VIDEO_FRAME_INTERVAL
        self.log.info("video_frame_extract_start", interval_s=interval)

        # Frames are saved to disk so they can be processed through the image pipeline
        frames_dir = Path(self.job.file_path).parent / "frames"
        frames_dir.mkdir(exist_ok=True)

        try:
            clip = VideoFileClip(self.job.file_path)
            duration = clip.duration
            timestamps = list(range(0, int(duration), interval))
            if not timestamps:
                timestamps = [0]

            last_hist: "np.ndarray | None" = None
            frames_kept = 0

            for ts in timestamps:
                try:
                    frame_rgb = clip.get_frame(ts)  # (H, W, 3) uint8 numpy array
                    hist = self._frame_histogram(frame_rgb)

                    # Skip near-duplicate frames (histogram correlation > 0.98)
                    if last_hist is not None:
                        similarity = self._histogram_similarity(hist, last_hist)
                        if similarity > 0.98:
                            continue

                    last_hist = hist

                    # Save frame as image file — follows the image pipeline
                    jpeg_bytes = self._numpy_to_jpeg(frame_rgb)
                    frame_path = frames_dir / f"frame_{int(ts):06d}s.jpg"
                    frame_path.write_bytes(jpeg_bytes)
                    self._frames.append((float(ts), str(frame_path)))
                    frames_kept += 1

                except Exception as frame_exc:
                    self.log.warning("frame_extract_error", ts=ts, error=str(frame_exc))
                    continue

            clip.close()
            self.log.info("video_frame_extract_done",
                          total_timestamps=len(timestamps), kept=frames_kept)

        except Exception as exc:
            self.log.warning("video_frame_extract_failed_skipping", error=str(exc))
            self._frames = []

    @staticmethod
    def _numpy_to_jpeg(frame_rgb) -> bytes:
        """Convert numpy RGB frame to JPEG bytes."""
        from PIL import Image
        import io
        img = Image.fromarray(frame_rgb, mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    @staticmethod
    def _frame_histogram(frame_rgb) -> "np.ndarray":
        import numpy as np
        gray = frame_rgb.mean(axis=2)
        hist, _ = np.histogram(gray, bins=64, range=(0, 256))
        return hist.astype(np.float32)

    @staticmethod
    def _histogram_similarity(h1, h2) -> float:
        """Pearson correlation between two histograms as a similarity score in [0, 1]."""
        import numpy as np
        denom = (np.linalg.norm(h1) * np.linalg.norm(h2))
        if denom == 0:
            return 0.0
        return float(np.dot(h1, h2) / denom)

    # ── Vision analysis of frames ─────────────────────────────────────────────

    def _analyse_frames(self, db) -> list[dict]:
        """
        Process each saved frame through the image pipeline (same OCR prompt as ImageProcessor).
        Reads each frame from its saved file on disk.
        Returns [{timestamp_s, timestamp_str, description}].
        """
        if not self._frames:
            return []

        results = []
        self.log.info("video_frame_vision_start", frame_count=len(self._frames))

        for ts_s, frame_path in self._frames:
            minutes = int(ts_s // 60)
            seconds = int(ts_s % 60)
            ts_str = f"{minutes:02d}:{seconds:02d}"

            try:
                with open(frame_path, "rb") as f:
                    image_data = f.read()

                # Use the same OCR extraction prompt as ImageProcessor — follows image pipeline
                ocr_markdown = self._call_vision_markdown(
                    _IMAGE_OCR_PROMPT, image_data, "image/jpeg", db
                )
                if ocr_markdown.strip():
                    frame_name = Path(frame_path).name
                    # Wrap with heading like ImageProcessor does
                    description = f"# {frame_name}\n\n{ocr_markdown.strip()}"
                    results.append({
                        "timestamp_s": ts_s,
                        "timestamp_str": ts_str,
                        "description": description,
                    })
            except Exception as exc:
                self.log.warning("frame_vision_failed", ts=ts_str, error=str(exc))
                continue

        self.log.info("video_frame_vision_done", described=len(results))
        return results

    # ── Merge and build markdown ───────────────────────────────────────────────

    def _build_summary(self, db) -> dict:
        """Orchestrate full video pipeline and return summary dict."""

        # ── Audio track ───────────────────────────────────────────────────────
        detected_lang = ""
        duration_s = 0.0
        speaker_embeddings: dict = {}
        if self._audio_path and os.path.exists(self._audio_path) and os.path.getsize(self._audio_path) > 0:
            whisper_segs, detected_lang, duration_s = transcribe_audio(
                self._client, self._audio_path, self.settings, self.log, db, self.job
            )
            speaker_segs, speaker_embeddings = diarize_audio(
                self._audio_path, self.log, self.settings.DIARIZATION_THRESHOLD,
                return_embeddings=True,
            )
            merged_segs = merge_transcript_diarization(whisper_segs, speaker_segs)
            self.log.info("video_audio_pipeline_done",
                          segment_count=len(merged_segs),
                          language=detected_lang,
                          duration_s=round(duration_s, 1))
        else:
            self.log.warning("video_no_audio_available")
            merged_segs = []

        # ── Visual track ──────────────────────────────────────────────────────
        visual_frames = self._analyse_frames(db)

        # ── Build unified markdown ────────────────────────────────────────────
        md = self._build_markdown(merged_segs, visual_frames)

        # ── LLM summary ───────────────────────────────────────────────────────
        summary = summarise_transcript(
            self._client, merged_segs, self.job.filename,
            self.settings, self.log, db, self.job,
            language=detected_lang, duration_seconds=duration_s,
        )

        summary["_chunk_text"] = md
        # Pass ECAPA speaker embeddings through to tasks.py for chunk metadata tagging.
        # base.py strips this key before DB serialization so the large vectors are never stored.
        summary["_speaker_embeddings"] = speaker_embeddings
        summary["visual_frames"] = [
            {"timestamp_s": f["timestamp_s"], "description": f["description"]}
            for f in visual_frames
        ]

        self.log.info(
            "video_processor_done",
            speaker_count=summary.get("speaker_count"),
            duration_seconds=summary.get("duration_seconds"),
            frames_analysed=len(visual_frames),
            md_chars=len(md),
        )
        return summary

    def _build_markdown(
        self,
        merged_segs: list[dict],
        visual_frames: list[dict],
    ) -> str:
        """
        Interleave transcript segments and visual frame descriptions by timestamp.

        Example output:
            # presentation.mp4

            ## Visual Frame [00:00]
            Slide: "Q2 Business Review" — title with company logo.

            ## [Speaker 1 at 00:05]
            Hello everyone, welcome to the quarterly review...

            ## Visual Frame [01:00]
            Bar chart showing monthly revenue Jan–May 2025.

            ## [Speaker 2 at 01:03]
            As you can see, growth has been consistent...
        """
        if not merged_segs and not visual_frames:
            return f"# {self.job.filename}\n\n*No extractable content found.*"

        # Build a unified event list sorted by timestamp
        events: list[dict] = []

        for seg in merged_segs:
            events.append({
                "type": "audio",
                "ts": seg["start"],
                "ts_str": seg["timestamp"],
                "speaker": seg["speaker"],
                "text": seg["text"],
            })

        for frame in visual_frames:
            minutes = int(frame["timestamp_s"] // 60)
            seconds = int(frame["timestamp_s"] % 60)
            events.append({
                "type": "visual",
                "ts": frame["timestamp_s"],
                "ts_str": f"{minutes:02d}:{seconds:02d}",
                "description": frame["description"],
            })

        events.sort(key=lambda e: e["ts"])

        lines = [f"# {self.job.filename}", ""]

        # Combine consecutive same-speaker audio segments under one heading
        i = 0
        while i < len(events):
            evt = events[i]

            if evt["type"] == "visual":
                lines.append(f"## Visual Frame [{evt['ts_str']}]")
                lines.append("")
                lines.append(evt["description"])
                lines.append("")
                i += 1

            else:
                # Combine consecutive same-speaker segments
                speaker = evt["speaker"]
                ts_str = evt["ts_str"]
                texts = [evt["text"]]
                j = i + 1
                while j < len(events) and events[j]["type"] == "audio" and events[j]["speaker"] == speaker:
                    texts.append(events[j]["text"])
                    j += 1

                lines.append(f"## [{speaker} at {ts_str}]")
                lines.append("")
                lines.append(" ".join(texts))
                lines.append("")
                i = j

        return "\n".join(lines)

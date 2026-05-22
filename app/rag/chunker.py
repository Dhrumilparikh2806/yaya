import re

from app.observability.logging import get_logger

log = get_logger()

_MIN_CHUNK_WORDS = 50


def chunk_text(
    text: str,
    job_id: str,
    filename: str,
    file_type: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[dict]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]

        if len(chunk_words) < _MIN_CHUNK_WORDS:
            break

        chunk_text_str = " ".join(chunk_words)

        # Extract the latest [Page N] marker before or within the chunk
        page_matches = re.findall(r"\[Page (\d+)\]", chunk_text_str)
        page_or_segment = f"page {page_matches[-1]}" if page_matches else "page 1"

        chunks.append({
            "text": chunk_text_str,
            "job_id": str(job_id),
            "filename": filename,
            "file_type": file_type,
            "chunk_index": chunk_index,
            "metadata": {"page_or_segment": page_or_segment},
        })
        chunk_index += 1

        if end == len(words):
            break
        start = end - overlap

    log.info(
        "chunk_text_done",
        job_id=str(job_id),
        total_chars=len(text),
        chunk_count=len(chunks),
    )
    return chunks


def chunk_video_segments(
    segments: list[dict],
    job_id: str,
    filename: str,
) -> list[dict]:
    return [
        {
            "text": f"[{seg['speaker']} at {seg['timestamp']}] {seg['text']}",
            "job_id": str(job_id),
            "filename": filename,
            "file_type": "video_audio",
            "chunk_index": i,
            "metadata": {
                "speaker": seg["speaker"],
                "timestamp": seg["timestamp"],
                "page_or_segment": f"{seg['speaker']} @ {seg['timestamp']}",
            },
        }
        for i, seg in enumerate(segments)
    ]

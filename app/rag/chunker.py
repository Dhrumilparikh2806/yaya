import re

from app.observability.logging import get_logger

log = get_logger()

_MIN_CHUNK_WORDS = 20

# Split on any H2 heading (## ...) that starts a new line
_SECTION_SPLIT = re.compile(r"(?=\n## )", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)", re.MULTILINE)


def _heading_label(section_text: str) -> str:
    """Return the first heading in a section as a human-readable citation label."""
    m = _HEADING_RE.search(section_text)
    if not m:
        return "content"
    label = m.group(1).strip()
    page_m = re.match(r"Page\s+(\d+)", label, re.IGNORECASE)
    return f"page {page_m.group(1)}" if page_m else label


def _split_by_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into word-count chunks with overlap."""
    words = text.split()
    out = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        piece = words[start:end]
        if len(piece) < _MIN_CHUNK_WORDS:
            break
        out.append(" ".join(piece))
        if end == len(words):
            break
        start = end - overlap
    return out


def chunk_markdown_hierarchical(
    text: str,
    job_id: str,
    filename: str,
    file_type: str,
    parent_size: int = 600,
    child_size: int = 150,
    parent_overlap: int = 50,
    child_overlap: int = 20,
) -> list[dict]:
    """
    Two-level chunking for hybrid retrieval.

    Child chunks (child_size words) are embedded + indexed in ChromaDB — small = precise match.
    Each child carries its parent text (parent_size words) in metadata — large = rich LLM context.
    BM25 and vector search both operate on child text; retrieval returns parent text to the LLM.
    """
    if not text or not text.strip():
        return []

    raw_sections = _SECTION_SPLIT.split(text)
    if len(raw_sections) <= 1:
        raw_sections = [text]

    chunks = []
    chunk_index = 0
    parent_index = 0

    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        label = _heading_label(section)
        parent_pieces = _split_by_words(section, parent_size, parent_overlap)

        for parent_piece in parent_pieces:
            parent_id = f"{job_id}_p{parent_index}"
            parent_index += 1
            child_pieces = _split_by_words(parent_piece, child_size, child_overlap)

            for child_piece in child_pieces:
                chunks.append({
                    "text": child_piece,
                    "job_id": str(job_id),
                    "filename": filename,
                    "file_type": file_type,
                    "chunk_index": chunk_index,
                    "metadata": {
                        "page_or_segment": label,
                        "parent_id": parent_id,
                        "parent_text": parent_piece,
                    },
                })
                chunk_index += 1

    log.info(
        "chunk_hierarchical_done",
        job_id=str(job_id),
        total_chars=len(text),
        chunk_count=len(chunks),
    )
    return chunks


def chunk_markdown(
    text: str,
    job_id: str,
    filename: str,
    file_type: str,
    chunk_size: int = 600,
    overlap: int = 50,
) -> list[dict]:
    """Flat markdown chunking (legacy path)."""
    if not text or not text.strip():
        return []

    raw_sections = _SECTION_SPLIT.split(text)
    if len(raw_sections) <= 1:
        raw_sections = [text]

    chunks = []
    chunk_index = 0

    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        label = _heading_label(section)
        pieces = _split_by_words(section, chunk_size, overlap)

        for piece in pieces:
            chunks.append({
                "text": piece,
                "job_id": str(job_id),
                "filename": filename,
                "file_type": file_type,
                "chunk_index": chunk_index,
                "metadata": {"page_or_segment": label},
            })
            chunk_index += 1

    log.info(
        "chunk_markdown_done",
        job_id=str(job_id),
        total_chars=len(text),
        chunk_count=len(chunks),
    )
    return chunks


# Legacy aliases
def chunk_text(text, job_id, filename, file_type, chunk_size=600, overlap=50):
    return chunk_markdown(text, job_id, filename, file_type, chunk_size, overlap)


def chunk_video_segments(segments: list[dict], job_id: str, filename: str) -> list[dict]:
    md = "\n\n".join(
        f"## [{s['speaker']} at {s['timestamp']}]\n\n{s['text']}"
        for s in segments
    )
    return chunk_markdown_hierarchical(md, job_id, filename, "video_audio")

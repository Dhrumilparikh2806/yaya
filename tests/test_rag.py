import pytest
import uuid


# ── Chunker tests ─────────────────────────────────────────────────────────────

def test_chunker_word_count():
    from app.rag.chunker import chunk_text
    text = "word " * 1000
    chunks = chunk_text(text, "job1", "file.txt", "pdf", chunk_size=100, overlap=20)
    for c in chunks:
        word_count = len(c["text"].split())
        assert word_count <= 120, f"Chunk too large: {word_count} words"
    assert len(chunks) > 0


def test_chunker_overlap():
    from app.rag.chunker import chunk_text
    text = " ".join([f"word{i}" for i in range(200)])
    chunks = chunk_text(text, "job1", "file.txt", "pdf", chunk_size=100, overlap=20)
    assert len(chunks) >= 2
    last_words_of_0 = chunks[0]["text"].split()[-20:]
    first_words_of_1 = chunks[1]["text"].split()[:20]
    assert last_words_of_0 == first_words_of_1


def test_chunker_page_metadata():
    from app.rag.chunker import chunk_text
    text = "[Page 1]\n" + "alpha " * 100 + "\n[Page 2]\n" + "beta " * 100
    chunks = chunk_text(text, "job1", "doc.pdf", "pdf", chunk_size=80, overlap=10)
    assert any("page" in c["metadata"]["page_or_segment"] for c in chunks)


def test_chunker_min_size_skip():
    from app.rag.chunker import chunk_text
    # Less than 50 words — should produce no chunks
    text = "only forty nine words " * 2  # 8 words
    chunks = chunk_text(text, "job1", "file.txt", "pdf", chunk_size=800, overlap=100)
    assert len(chunks) == 0


def test_chunk_video_segments():
    from app.rag.chunker import chunk_video_segments
    segments = [
        {"speaker": "Speaker 1", "timestamp": "00:05", "text": "Hello, welcome."},
        {"speaker": "Speaker 2", "timestamp": "00:10", "text": "Thanks for joining."},
    ]
    chunks = chunk_video_segments(segments, "job2", "meeting.mp4")
    assert len(chunks) == 2
    assert chunks[0]["metadata"]["page_or_segment"] == "Speaker 1 @ 00:05"
    assert chunks[1]["metadata"]["speaker"] == "Speaker 2"
    assert chunks[0]["file_type"] == "video_audio"
    assert "Speaker 1 at 00:05" in chunks[0]["text"]


def test_chunk_video_segments_empty():
    from app.rag.chunker import chunk_video_segments
    assert chunk_video_segments([], "job3", "audio.mp3") == []


# ── VectorStore tests (in-memory ChromaDB) ───────────────────────────────────

@pytest.fixture
def chroma_collection():
    import chromadb
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        name="test_collection",
        metadata={"hnsw:space": "cosine"},
    )
    yield collection
    client.delete_collection("test_collection")


def _make_embed(dim=768, hot_index=0):
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def test_vectorstore_add_and_search(chroma_collection):
    from app.rag.vectorstore import add_chunks, search

    job_id = str(uuid.uuid4())
    chunks = [
        {"text": "chunk about AI", "job_id": job_id, "filename": "ai.pdf",
         "file_type": "pdf", "chunk_index": 0, "metadata": {"page_or_segment": "page 1"}},
        {"text": "chunk about cooking", "job_id": job_id, "filename": "ai.pdf",
         "file_type": "pdf", "chunk_index": 1, "metadata": {"page_or_segment": "page 2"}},
        {"text": "chunk about music", "job_id": job_id, "filename": "ai.pdf",
         "file_type": "pdf", "chunk_index": 2, "metadata": {"page_or_segment": "page 3"}},
    ]
    embeddings = [_make_embed(hot_index=0), _make_embed(hot_index=1), _make_embed(hot_index=2)]
    add_chunks(chroma_collection, chunks, embeddings)

    results = search(chroma_collection, _make_embed(hot_index=0), top_k=3)
    assert len(results) == 3
    assert results[0]["text"] == "chunk about AI"
    assert results[0]["score"] > results[1]["score"]


def test_vectorstore_job_id_filter(chroma_collection):
    from app.rag.vectorstore import add_chunks, search

    job_a = str(uuid.uuid4())
    job_b = str(uuid.uuid4())

    chunks_a = [{"text": "A text", "job_id": job_a, "filename": "a.pdf",
                 "file_type": "pdf", "chunk_index": 0, "metadata": {"page_or_segment": "page 1"}}]
    chunks_b = [{"text": "B text", "job_id": job_b, "filename": "b.pdf",
                 "file_type": "pdf", "chunk_index": 0, "metadata": {"page_or_segment": "page 1"}}]
    add_chunks(chroma_collection, chunks_a, [_make_embed(hot_index=0)])
    add_chunks(chroma_collection, chunks_b, [_make_embed(hot_index=1)])

    results = search(chroma_collection, _make_embed(hot_index=0), top_k=5, job_ids=[job_a])
    assert len(results) == 1
    assert results[0]["job_id"] == job_a


def test_vectorstore_delete(chroma_collection):
    from app.rag.vectorstore import add_chunks, delete_job_chunks, search

    job_id = str(uuid.uuid4())
    chunks = [{"text": "deletable chunk", "job_id": job_id, "filename": "del.pdf",
               "file_type": "pdf", "chunk_index": 0, "metadata": {"page_or_segment": "page 1"}}]
    add_chunks(chroma_collection, chunks, [_make_embed(hot_index=5)])
    delete_job_chunks(chroma_collection, job_id)

    results = search(chroma_collection, _make_embed(hot_index=5), top_k=5, job_ids=[job_id])
    assert len(results) == 0

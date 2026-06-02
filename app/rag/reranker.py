"""
Cross-encoder reranker (sentence-transformers ms-marco-MiniLM-L-6-v2).

The model is lazy-loaded into a module-level singleton on first use.

Python 3.13 compatibility: sentence-transformers / PyTorch crash when first
initialised from a non-TTY subprocess (e.g. uvicorn with redirected stdout).
The reranker is disabled on Python 3.13+ by default.  Set GEMINIRAG_RERANKER=1
to force-enable it — safe on Python 3.11 / Docker.

rerank() falls back gracefully to returning the top-k RRF-ordered results when
the reranker is disabled or raises an exception, so the RAG pipeline never
hard-fails because of reranker unavailability.
"""

import os
import sys

from app.observability.logging import get_logger

log = get_logger()

_model = None
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# On Python 3.13+, sentence-transformers / PyTorch triggers native-code crashes
# when initialised in a subprocess or thread with non-TTY stdout (e.g. uvicorn
# with redirected output). Disable the reranker in those environments; the RAG
# pipeline falls back to RRF-ordered top-k results which are still high quality.
# This flag can be overridden by setting GEMINIRAG_RERANKER=1 in .env.
_RERANKER_ENABLED = (
    sys.version_info < (3, 13)
    or os.environ.get("GEMINIRAG_RERANKER", "0") == "1"
)


def _get_model():
    global _model
    if not _RERANKER_ENABLED:
        return None
    if _model is None:
        from sentence_transformers import CrossEncoder
        log.info("reranker_load", model=_MODEL_NAME)
        _model = CrossEncoder(_MODEL_NAME, max_length=512)
    return _model


def start_bg_load():
    """No-op — kept for API compatibility. Reranker loads lazily on first call."""


def rerank(question: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Re-rank chunks using a cross-encoder.
    Falls back gracefully to RRF-ordered top-k when reranker is disabled or fails.
    """
    if not chunks:
        return chunks

    m = _get_model()
    if m is None:
        log.info("reranker_passthrough", top_k=top_k, reason="disabled_or_unavailable")
        return chunks[:top_k]

    try:
        pairs = [(question, c["text"][:512]) for c in chunks]
        scores = m.predict(pairs)
        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = float(score)
        reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
        log.info("reranker_done", input_chunks=len(chunks), output_chunks=top_k)
        return reranked[:top_k]
    except Exception as exc:
        log.warning("reranker_predict_failed", error=str(exc))
        return chunks[:top_k]

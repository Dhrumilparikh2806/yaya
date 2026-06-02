"""
Offline RAGAS baseline evaluation.
Usage: py scripts/ragas_baseline.py [--test-set /path/to/test_set.json]
"""
import json
import sys
import time
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, create_engine, select
import os

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


def _rag_query_with_retry(question, job_ids, user_id, db, settings, max_wait=600):
    """Retrieve chunks and generate answer. Bypasses engine.py to avoid importing
    the CrossEncoder reranker (sentence-transformers/PyTorch), which crashes when
    loaded in the same process as ragas + fastembed (ONNX Runtime)."""
    # Import retrieval components directly — do NOT import app.rag.engine or app.rag.reranker
    from app.rag.embedder import embed_query
    from app.rag.vectorstore import get_chroma_client, get_or_create_collection, search, rrf_merge
    from app.rag.bm25_index import load_bm25, build_bm25, search_bm25
    import groq as groq_sdk

    q_embedding = embed_query(question, settings)
    client = get_chroma_client(settings)
    collection = get_or_create_collection(client, settings)

    vector_chunks = search(collection, q_embedding, top_k=settings.RAG_TOP_K * 2, job_ids=job_ids)
    top_vector_score = vector_chunks[0]["score"] if vector_chunks else 0.0

    if top_vector_score < settings.CONFIDENCE_THRESHOLD:
        return "I couldn't find sufficiently relevant information in your documents to answer this question confidently.", []

    index_data = load_bm25(settings) or build_bm25(collection, settings)
    bm25_chunks = search_bm25(index_data, question, top_k=settings.RAG_TOP_K * 2, job_ids=job_ids)
    rrf_chunks = rrf_merge(vector_chunks, bm25_chunks, top_k=settings.RAG_TOP_K * 2)
    # Use top RAG_TOP_K chunks without cross-encoder (avoids PyTorch/ONNX conflict in eval process)
    chunks = rrf_chunks[:settings.RAG_TOP_K]

    if not chunks:
        return "No documents found to search. Please upload and process files first.", []

    full_contexts = [c["text"] for c in chunks]

    _MAX_CHUNK_CHARS = 1200
    context_parts = [
        f"[{i}] Source: {c['filename']} ({c['page_or_segment']})\n{c['text'][:_MAX_CHUNK_CHARS]}"
        for i, c in enumerate(chunks, 1)
    ]
    user_prompt = (
        f"Context:\n{chr(10).join(context_parts)}\n\nQuestion: {question}\n\nAnswer (with [n] citation markers):"
    )

    groq_client = groq_sdk.Groq(api_key=settings.GROQ_API_KEY)
    for attempt in range(5):
        try:
            resp = groq_client.chat.completions.create(
                model=settings.GROQ_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": (
                        "You are a document Q&A assistant. Answer ONLY from the numbered context excerpts provided. "
                        "Do NOT use any knowledge from outside these excerpts.\n"
                        "Every factual claim must be followed by a [n] citation marker. "
                        "If the information is not in the context, say: "
                        "'The provided documents do not contain this information.'"
                    )},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=512,
            )
            answer = resp.choices[0].message.content
            return answer, full_contexts
        except groq_sdk.RateLimitError as e:
            wait = 60 * (attempt + 1)
            print(f"  [RAG 429] waiting {wait}s... ({e!s:.80})")
            time.sleep(wait)
    return "Rate limit — could not generate answer.", full_contexts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-set", default="C:/tmp/ragas_test_set.json")
    args = parser.parse_args()

    test_set_path = Path(args.test_set)
    if not test_set_path.exists():
        print(f"[ERROR] Test set not found: {test_set_path}")
        sys.exit(1)

    with open(test_set_path) as f:
        test_set = json.load(f)

    print(f"Loaded {len(test_set)} Q&A pairs from {test_set_path}")

    from app.config import settings
    from app.evaluation.ragas_eval import compute_ragas_scores

    results = []
    col_w = 45

    print(f"\n{'Question':<{col_w}} {'Faith':>6} {'AnswRel':>7} {'CtxPrec':>8} {'CtxRec':>7} {'AnsCorr':>8}")
    print("-" * (col_w + 42))

    with Session(engine) as db:
        for item in test_set:
            question = item["question"]
            ground_truth = item.get("ground_truth")
            job_id = item.get("job_id")
            job_ids = [job_id] if job_id else None

            from app.models.db import Job, User
            user_id = None
            if job_id:
                job = db.get(Job, __import__("uuid").UUID(job_id))
                if job:
                    user_id = job.user_id
            if not user_id:
                user = db.exec(select(User)).first()
                user_id = user.id if user else None

            try:
                answer, full_contexts = _rag_query_with_retry(
                    question, job_ids, user_id, db, settings
                )
                if not full_contexts:
                    full_contexts = ["(no context retrieved)"]

                # Truncate each context to 600 chars for RAGAS eval to stay within
                # 8b model's 6K TPM limit (6 chunks × 600 chars ≈ 3600 chars + overhead)
                ragas_contexts = [c[:600] for c in full_contexts]

                scores = compute_ragas_scores(
                    question=question,
                    answer=answer,
                    contexts=ragas_contexts,
                    ground_truth=ground_truth,
                    settings=settings,
                )

                faith = scores.get("faithfulness", float("nan"))
                rel = scores.get("answer_relevancy", float("nan"))
                prec = scores.get("context_precision", float("nan"))
                rec = scores.get("context_recall", float("nan"))
                corr = scores.get("answer_correctness", float("nan"))

                q_short = question[:col_w - 3] + "..." if len(question) > col_w else question
                print(f"{q_short:<{col_w}} {faith:>6.3f} {rel:>7.3f} {prec:>8.3f} {rec:>7.3f} {corr:>8.3f}")

                results.append({
                    "question": question,
                    "ground_truth": ground_truth,
                    "answer": answer,
                    "scores": scores,
                })

            except Exception as e:
                print(f"[SKIP] {question[:50]}: {e}")
                results.append({"question": question, "error": str(e)})

            # Small gap between questions to ease rate limits
            time.sleep(5)

    metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
    sums = {k: 0.0 for k in metric_keys}
    counts = {k: 0 for k in metric_keys}
    for r in results:
        for k in metric_keys:
            v = r.get("scores", {}).get(k)
            if isinstance(v, float) and not __import__("math").isnan(v):
                sums[k] += v
                counts[k] += 1
    avgs = {k: round(sums[k] / counts[k], 4) if counts[k] else None for k in metric_keys}

    print("\n" + "=" * 60)
    print("BASELINE AVERAGES")
    print("=" * 60)
    for k, v in avgs.items():
        target = {"faithfulness": 0.8, "context_precision": 0.6}.get(k, 0.7)
        status = "PASS" if v and v >= target else "BELOW TARGET"
        print(f"  {k:<25} {str(v) if v is not None else 'N/A':>8}  (target >= {target}) {status}")

    out_path = Path("C:/tmp/ragas_baseline.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"results": results, "averages": avgs}, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()

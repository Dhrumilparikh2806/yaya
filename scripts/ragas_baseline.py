"""
Offline RAGAS baseline evaluation.
Usage: py scripts/ragas_baseline.py [--test-set /path/to/test_set.json]

Loads /tmp/ragas_test_set.json (or --test-set path), runs RAG engine for each
Q&A pair, computes RAGAS scores with ground_truth, prints a summary table,
and saves results to /tmp/ragas_baseline.json.
"""
import json
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, create_engine, select
import os


DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-set", default="C:/tmp/ragas_test_set.json")
    args = parser.parse_args()

    test_set_path = Path(args.test_set)
    if not test_set_path.exists():
        print(f"[ERROR] Test set not found: {test_set_path}")
        print("Create a JSON file with this structure:")
        print(json.dumps([{
            "question": "What is the main contribution of the paper?",
            "ground_truth": "The paper proposes...",
            "job_id": "paste-job-uuid-here"
        }], indent=2))
        sys.exit(1)

    with open(test_set_path) as f:
        test_set = json.load(f)

    print(f"Loaded {len(test_set)} Q&A pairs from {test_set_path}")

    from app.config import settings
    from app.rag import engine as rag_engine
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

            # Find a user to query as (use first user that owns the job)
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
                result = rag_engine.query(
                    question=question,
                    job_ids=job_ids,
                    user_id=user_id,
                    db=db,
                    settings=settings,
                )
                answer = result["answer"]
                contexts = [c["excerpt"] for c in result.get("citations", [])]
                if not contexts:
                    contexts = ["(no context retrieved)"]

                scores = compute_ragas_scores(
                    question=question,
                    answer=answer,
                    contexts=contexts,
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

    # Compute averages
    if results:
        metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
        sums = {k: 0.0 for k in metric_keys}
        counts = {k: 0 for k in metric_keys}
        for r in results:
            for k in metric_keys:
                v = r.get("scores", {}).get(k)
                if isinstance(v, float):
                    sums[k] += v
                    counts[k] += 1
        avgs = {k: round(sums[k] / counts[k], 4) if counts[k] else None for k in metric_keys}

        print("\n" + "=" * 60)
        print("BASELINE AVERAGES")
        print("=" * 60)
        for k, v in avgs.items():
            target = {"faithfulness": 0.8, "context_precision": 0.6}.get(k, 0.7)
            status = "PASS" if v and v >= target else "BELOW TARGET"
            print(f"  {k:<25} {v if v else 'N/A':>6}  (target ≥ {target}) {status}")

        out_path = Path("C:/tmp/ragas_baseline.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({"results": results, "averages": avgs}, f, indent=2)
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()

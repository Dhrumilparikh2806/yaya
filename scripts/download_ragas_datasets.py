"""
Download MS MARCO v1.1 and Natural Questions (dev) samples for RAGAS baseline.

Saves to:
  Data set/ragas_eval/ms_marco_samples.json
  Data set/ragas_eval/natural_questions_samples.json

Each file is a list of {"question": ..., "ground_truth": ...} dicts ready
for use in ragas_baseline.py (add job_id before running the baseline).
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "Data set" / "ragas_eval"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_SIZE = 50  # Q&A pairs per dataset


def download_ms_marco():
    print("Downloading MS MARCO v1.1 (validation split, streaming) ...")
    from datasets import load_dataset

    ds = load_dataset(
        "microsoft/ms_marco",
        "v1.1",
        split="validation",
        streaming=True,
        trust_remote_code=True,
    )

    samples = []
    for row in ds:
        answers = row.get("answers", [])
        if not answers or answers == ["No Answer Present."]:
            continue
        samples.append({
            "question": row["query"],
            "ground_truth": answers[0],
        })
        if len(samples) >= SAMPLE_SIZE:
            break

    out = OUT_DIR / "ms_marco_samples.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(samples)} samples -> {out}")
    return samples


def download_natural_questions():
    print("Downloading Natural Questions dev (streaming) ...")
    from datasets import load_dataset

    ds = load_dataset(
        "google-research-datasets/natural_questions",
        "dev",
        split="validation",
        streaming=True,
        trust_remote_code=True,
    )

    samples = []
    for row in ds:
        question = row["question"]["text"]
        # short_answers are spans; pick the first non-empty one
        annotations = row.get("annotations", {})
        short_answers = annotations.get("short_answers", [])
        ground_truth = None
        for sa in short_answers:
            texts = sa.get("text", [])
            if texts:
                ground_truth = texts[0]
                break
        if not ground_truth:
            continue
        samples.append({
            "question": question,
            "ground_truth": ground_truth,
        })
        if len(samples) >= SAMPLE_SIZE:
            break

    out = OUT_DIR / "natural_questions_samples.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(samples)} samples -> {out}")
    return samples


if __name__ == "__main__":
    marco = download_ms_marco()
    nq = download_natural_questions()

    total = len(marco) + len(nq)
    print(f"\nDone. {total} total Q&A pairs saved to {OUT_DIR}")
    print("\nNext step: run ragas_baseline.py after uploading documents and")
    print("adding job_id fields to the samples you want to evaluate.")

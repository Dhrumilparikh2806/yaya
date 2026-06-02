"""
RAGAS quality evaluation for RAG query responses.

compute_ragas_scores() is called asynchronously by the compute_ragas Celery
task after every successful RAG query.  It never blocks the query response.

Metrics computed
----------------
Always (no ground truth needed):
  faithfulness       — every claim in the answer is grounded in the context.
  answer_relevancy   — the answer addresses the question asked.

With ground_truth only:
  context_precision  — proportion of retrieved chunks that were relevant.
  context_recall     — proportion of ground truth covered by the context.
  answer_correctness — answer matches the reference answer.

Implementation notes
--------------------
- Uses Groq (GROQ_PROCESSING_MODEL = llama-3.1-8b-instant) via LangChain as
  the evaluator LLM.  The 500k TPD quota on llama-3.1-8b-instant means RAGAS
  rarely hits rate limits even at moderate query volumes.
- RAGAS default strictness=3 batches 3 LLM calls per metric in one request;
  Groq only supports n=1 so strictness is set to 1.
- Each context is truncated to 800 chars before sending to RAGAS to stay
  within the 6k TPM per-request limit.
- Auto-retries once after 65 s on 429 rate-limit errors.
"""

import os
import warnings
os.environ["RAGAS_DO_NOT_TRACK"] = "true"
# Suppress Python 3.14 asyncio "Event loop is closed" noise from httpx cleanup
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from app.observability.logging import get_logger

log = get_logger()


def get_ragas_llm(settings):
    from langchain_groq import ChatGroq
    from ragas.llms import LangchainLLMWrapper
    # Use llama-3.1-8b-instant for RAGAS evaluation:
    #   - 500,000 TPD (vs 100,000 for llama-3.3-70b) — won't exhaust daily quota
    #   - Context truncation to 800 chars/chunk keeps each request under 6k TPM
    # n=1: Groq only supports single generation per request.
    return LangchainLLMWrapper(ChatGroq(
        model=settings.GROQ_PROCESSING_MODEL,
        api_key=settings.GROQ_API_KEY,
        n=1,
    ))


def get_ragas_embeddings(settings):
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    return LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL))


def compute_ragas_scores(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str | None,
    settings,
) -> dict:
    try:
        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.metrics import (
            Faithfulness,
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            AnswerCorrectness,
        )

        # Truncate each context to 800 chars to keep total payload inside
        # Groq's 6k TPM limit. RAGAS sends all contexts + answer + question
        # in a single prompt; without truncation large chunks cause 413 errors.
        truncated_contexts = [c[:800] for c in (contexts or [])]

        sample = SingleTurnSample(
            user_input=question,
            response=answer,
            retrieved_contexts=truncated_contexts,
            reference=ground_truth,
        )
        dataset = EvaluationDataset(samples=[sample])

        llm = get_ragas_llm(settings)
        embeddings = get_ragas_embeddings(settings)

        # Faithfulness + AnswerRelevancy work without ground truth.
        # ContextPrecision, ContextRecall, AnswerCorrectness all require a
        # reference answer — only include them when ground_truth is provided.
        # strictness=1 → single question generation per sample.
        # Groq only supports n=1 per request; RAGAS default strictness=3
        # batches n=3 in one call which Groq rejects with 400.
        metrics = [Faithfulness(), AnswerRelevancy(strictness=1)]
        if ground_truth:
            metrics += [ContextPrecision(), ContextRecall(), AnswerCorrectness()]

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
        )
        scores = result.to_pandas().iloc[0].to_dict()
        metric_keys = ["faithfulness", "answer_relevancy"]
        if ground_truth:
            metric_keys += ["context_precision", "context_recall", "answer_correctness"]
        return {k: float(scores[k]) for k in metric_keys if k in scores and str(scores[k]) != "nan"}

    except Exception as e:
        err_str = str(e)
        # Auto-retry once on rate limit (TPM/TPD) after a 65-second backoff
        if "429" in err_str or "rate_limit" in err_str.lower() or "RateLimitError" in err_str:
            log.warning("ragas_rate_limit_retry", wait_s=65)
            import time as _time; _time.sleep(65)
            try:
                result = evaluate(dataset=dataset, metrics=metrics, llm=llm, embeddings=embeddings)
                scores = result.to_pandas().iloc[0].to_dict()
                return {k: float(scores[k]) for k in metric_keys if k in scores and str(scores[k]) != "nan"}
            except Exception as e2:
                log.error("ragas_eval_error_after_retry", error=str(e2))
                return {"error": str(e2)}
        log.error("ragas_eval_error", error=err_str)
        return {"error": err_str}

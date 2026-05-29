import os
import warnings
os.environ["RAGAS_DO_NOT_TRACK"] = "true"
warnings.filterwarnings("ignore")

from app.observability.logging import get_logger

log = get_logger()


def get_ragas_llm(settings):
    from langchain_groq import ChatGroq
    from ragas.llms import LangchainLLMWrapper
    # n=1: Groq only supports single generation; RAGAS default of n=3 causes failures
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

        sample = SingleTurnSample(
            user_input=question,
            response=answer,
            retrieved_contexts=contexts,
            reference=ground_truth,
        )
        dataset = EvaluationDataset(samples=[sample])

        llm = get_ragas_llm(settings)
        embeddings = get_ragas_embeddings(settings)

        metrics = [Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()]
        if ground_truth:
            metrics.append(AnswerCorrectness())

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
        )
        scores = result.to_pandas().iloc[0].to_dict()
        metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        if ground_truth:
            metric_keys.append("answer_correctness")
        return {k: float(scores[k]) for k in metric_keys if k in scores and str(scores[k]) != "nan"}

    except Exception as e:
        log.error("ragas_eval_error", error=str(e))
        return {"error": str(e)}

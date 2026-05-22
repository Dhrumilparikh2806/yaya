from app.observability.logging import get_logger

log = get_logger()


def get_ragas_llm(settings):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
    )


def get_ragas_embeddings(settings):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(
        model=settings.GEMINI_EMBEDDING_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
    )


def compute_ragas_scores(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str | None,
    settings,
) -> dict:
    try:
        import nest_asyncio
        nest_asyncio.apply()

        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics.collections import (
            AnswerCorrectness,
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        sample = SingleTurnSample(
            user_input=question,
            response=answer,
            retrieved_contexts=contexts,
            reference=ground_truth,
        )
        dataset = EvaluationDataset(samples=[sample])

        metrics = [Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()]
        if ground_truth:
            metrics.append(AnswerCorrectness())

        llm = LangchainLLMWrapper(get_ragas_llm(settings))
        embeddings = LangchainEmbeddingsWrapper(get_ragas_embeddings(settings))

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
        )
        scores = result.to_pandas().iloc[0].to_dict()
        # Keep only numeric metric scores
        metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        if ground_truth:
            metric_keys.append("answer_correctness")
        return {k: float(scores[k]) for k in metric_keys if k in scores}

    except Exception as e:
        log.error("ragas_eval_error", error=str(e))
        return {"error": str(e)}

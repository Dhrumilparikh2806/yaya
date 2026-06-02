"""
Test two approaches:
A) Old ragas.metrics + LangchainLLMWrapper + evaluate()
B) Collections metrics + ascore() called directly per metric
"""
import warnings; warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv; load_dotenv()
from app.config import settings

# === Approach A: old ragas.metrics with LangchainLLMWrapper ===
print("=== Approach A: old ragas.metrics + LangchainLLMWrapper ===")
try:
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_groq import ChatGroq
    from langchain_community.embeddings import FastEmbedEmbeddings

    llm = LangchainLLMWrapper(ChatGroq(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY))
    emb = LangchainEmbeddingsWrapper(FastEmbedEmbeddings(model_name=settings.EMBEDDING_MODEL))

    sample = SingleTurnSample(
        user_input="What is the capital of France?",
        response="The capital of France is Paris.",
        retrieved_contexts=["Paris is the capital and most populous city of France."],
        reference="Paris is the capital of France.",
    )
    dataset = EvaluationDataset(samples=[sample])
    result = evaluate(
        dataset=dataset,
        metrics=[Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()],
        llm=llm,
        embeddings=emb,
    )
    print("Approach A result:")
    print(result.to_pandas()[["faithfulness","answer_relevancy","context_precision","context_recall"]].to_string())
except Exception as e:
    print(f"Approach A FAILED: {e}")

# === Approach B: collections metrics ascore() directly ===
print("\n=== Approach B: collections metrics + ascore() ===")
try:
    import asyncio
    from openai import OpenAI
    from ragas.llms import llm_factory
    from ragas.embeddings import HuggingFaceEmbeddings
    from ragas.metrics.collections import Faithfulness as CF, AnswerRelevancy as CAR, ContextPrecision as CCP, ContextRecall as CCR

    oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    llm = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)
    emb = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)

    async def run_scores():
        response = "The capital of France is Paris."
        contexts = ["Paris is the capital and most populous city of France."]
        reference = "Paris is the capital of France."
        f = await CF(llm=llm).ascore(response=response, retrieved_contexts=contexts)
        ar = await CAR(llm=llm, embeddings=emb).ascore(response=response, retrieved_contexts=contexts)
        print(f"Faithfulness: {f}, AnswerRelevancy: {ar}")
    asyncio.run(run_scores())
except Exception as e:
    print(f"Approach B FAILED: {e}")
    import traceback; traceback.print_exc()

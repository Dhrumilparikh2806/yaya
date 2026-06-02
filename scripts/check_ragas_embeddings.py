"""Dev utility — validate that embeddings are stored correctly in ChromaDB."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

from app.config import settings
from openai import OpenAI
from ragas.llms import llm_factory

oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
llm = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)

# Try different embedding approaches
# 1. LangchainEmbeddingsWrapper
try:
    from langchain_community.embeddings import FastEmbedEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    emb = LangchainEmbeddingsWrapper(FastEmbedEmbeddings(model_name=settings.EMBEDDING_MODEL))
    print(f"LangchainEmbeddingsWrapper: OK -> {type(emb)}")
except Exception as e:
    print(f"LangchainEmbeddingsWrapper FAIL: {e}")

# 2. RAGAS embedding_factory with openai-compat
try:
    from ragas.embeddings.base import embedding_factory
    re = embedding_factory(provider="openai", model="text-embedding-3-small", client=oai_client)
    print(f"embedding_factory openai-compat: OK -> {type(re)}")
except Exception as e:
    print(f"embedding_factory openai-compat FAIL: {e}")

# 3. Test a quick RAGAS evaluation with the working llm
try:
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics.collections import AnswerRelevancy

    sample = SingleTurnSample(
        user_input="What is the capital of France?",
        response="The capital of France is Paris.",
        retrieved_contexts=["Paris is the capital city of France."],
        reference="Paris is the capital of France.",
    )
    dataset = EvaluationDataset(samples=[sample])

    # Try with LangchainEmbeddingsWrapper
    from langchain_community.embeddings import FastEmbedEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    emb = LangchainEmbeddingsWrapper(FastEmbedEmbeddings(model_name=settings.EMBEDDING_MODEL))

    result = evaluate(dataset=dataset, metrics=[AnswerRelevancy(llm=llm, embeddings=emb)])
    print(f"Evaluation test: OK -> {result.to_pandas().to_dict()}")
except Exception as e:
    print(f"Evaluation test FAIL: {e}")

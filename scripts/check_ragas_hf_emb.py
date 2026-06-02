"""Dev utility — test HuggingFace embedding model availability for RAGAS."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")
from app.config import settings

from openai import OpenAI
from ragas.llms import llm_factory
from ragas.embeddings import HuggingFaceEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics.collections import AnswerRelevancy, Faithfulness, ContextPrecision, ContextRecall, AnswerCorrectness

import warnings; warnings.filterwarnings("ignore")

oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
llm = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)

# HuggingFaceEmbeddings from RAGAS
try:
    emb = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)
    print(f"HuggingFaceEmbeddings: OK -> {type(emb)}")
except Exception as e:
    print(f"HuggingFaceEmbeddings FAIL: {e}")
    import traceback; traceback.print_exc()
    import sys; sys.exit(1)

# Quick test
sample = SingleTurnSample(
    user_input="What is the capital of France?",
    response="The capital of France is Paris.",
    retrieved_contexts=["Paris is the capital and most populous city of France."],
    reference="Paris is the capital of France.",
)
dataset = EvaluationDataset(samples=[sample])

metrics = [
    Faithfulness(llm=llm),
    AnswerRelevancy(llm=llm, embeddings=emb),
    ContextPrecision(llm=llm),
    ContextRecall(llm=llm),
]

print("Running evaluation...")
result = evaluate(dataset=dataset, metrics=metrics)
print("Result:")
print(result.to_pandas()[["faithfulness","answer_relevancy","context_precision","context_recall"]].to_string())

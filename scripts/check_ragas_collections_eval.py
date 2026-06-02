"""Dev utility — inspect RAGAS evaluation output across collections."""
import warnings; warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv; load_dotenv()
from app.config import settings

# Try calling a collections metric score directly (not via evaluate())
from openai import OpenAI
from ragas.llms import llm_factory
from ragas.embeddings import HuggingFaceEmbeddings
from ragas.metrics.collections import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall

oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
llm = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)
emb = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)

f = Faithfulness(llm=llm)
print("Faithfulness type:", type(f))
print("Faithfulness methods:", [m for m in dir(f) if not m.startswith('_')])

# Try score() directly
import asyncio

async def test():
    from ragas.dataset_schema import SingleTurnSample as ST
    sample = ST(
        user_input="What is the capital of France?",
        response="The capital of France is Paris.",
        retrieved_contexts=["Paris is the capital and most populous city of France."],
        reference="Paris is the capital of France.",
    )
    score = await f.ascore(sample)
    print(f"Faithfulness score: {score}")

asyncio.run(test())

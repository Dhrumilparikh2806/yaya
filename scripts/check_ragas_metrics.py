"""Dev utility — print current RAGAS metric averages from query_history."""
import warnings; warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv; load_dotenv()

# Check metric classes
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
print("ragas.metrics imports:", Faithfulness, AnswerRelevancy)

from ragas.metrics.collections import Faithfulness as F2
print("collections Faithfulness:", F2)

# Check if they are the same
print("Same?", Faithfulness is F2)

# Check inspect
import inspect
print("ragas.metrics.Faithfulness module:", inspect.getmodule(Faithfulness).__name__)
print("collections.Faithfulness module:", inspect.getmodule(F2).__name__)

# Try init
from openai import OpenAI
from app.config import settings
from ragas.llms import llm_factory
from ragas.embeddings import HuggingFaceEmbeddings

oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
llm = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)
emb = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)

m = Faithfulness(llm=llm)
print("Initialized metric:", type(m), hasattr(m, '__class__'))

from ragas.metrics import MetricWithLLM
print("Is MetricWithLLM?", isinstance(m, MetricWithLLM))

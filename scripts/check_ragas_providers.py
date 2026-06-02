"""Dev utility — test RAGAS LLM and embedding provider connectivity."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

from app.config import settings

# Test llm_factory with groq provider
from ragas.llms import llm_factory
import groq as groq_sdk

groq_client = groq_sdk.Groq(api_key=settings.GROQ_API_KEY)
try:
    llm = llm_factory(model=settings.GROQ_MODEL, provider="groq", client=groq_client)
    print(f"groq provider: OK -> {type(llm)}")
except Exception as e:
    print(f"groq provider FAIL: {e}")

# Test with openai-compat base_url approach
try:
    from openai import OpenAI
    oai_client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    llm2 = llm_factory(model=settings.GROQ_MODEL, provider="openai", client=oai_client)
    print(f"openai-compat provider: OK -> {type(llm2)}")
except Exception as e:
    print(f"openai-compat provider FAIL: {e}")

# Test embeddings - use fastembed directly
from ragas.embeddings.base import embedding_factory
try:
    from fastembed import TextEmbedding
    te = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
    print(f"fastembed TextEmbedding: OK")
except Exception as e:
    print(f"fastembed FAIL: {e}")

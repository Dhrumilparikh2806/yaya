"""Dev utility — display RAGAS scores from the latest query_history rows."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

from app.config import settings
from app.rag.engine import _resolve_chunks_and_context

q = "What is the total combined pipeline value mentioned in the sales pipeline review?"
print(f"CONFIDENCE_THRESHOLD={settings.CONFIDENCE_THRESHOLD}")

result = _resolve_chunks_and_context(q, None, settings)
print(f"early_return={result['early_return']}")
if not result["early_return"]:
    print(f"chunks={len(result['chunks'])}, avg_score={result['avg_score']:.4f}")
    print(f"top chunk rerank_score={result['chunks'][0].get('rerank_score', 'n/a'):.4f}")
else:
    print(f"answer={result['payload']['answer'][:100]}")

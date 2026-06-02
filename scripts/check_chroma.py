"""Dev utility — verify ChromaDB collection contents and chunk count."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

from app.config import settings
from app.rag.vectorstore import get_chroma_client, get_or_create_collection

client = get_chroma_client(settings)
col = get_or_create_collection(client, settings)
count = col.count()
print(f"Total chunks in ChromaDB: {count}")

peek = col.peek(limit=5)
for i, (doc, meta) in enumerate(zip(peek["documents"], peek["metadatas"])):
    print(f"\n--- Chunk {i+1} ---")
    print(f"  file: {meta.get('filename','?')}  type: {meta.get('file_type','?')}")
    print(f"  text: {doc[:200]}")

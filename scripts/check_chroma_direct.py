"""Check ChromaDB data directly using PersistentClient (no server needed)."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

import chromadb

chroma_path = r"C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag\chroma"
client = chromadb.PersistentClient(path=chroma_path)

collections = client.list_collections()
print(f"Collections: {[c.name for c in collections]}")

for col in collections:
    c = client.get_collection(col.name)
    count = c.count()
    print(f"\nCollection '{col.name}': {count} chunks")
    if count > 0:
        peek = c.peek(limit=3)
        for i, (doc, meta) in enumerate(zip(peek["documents"], peek["metadatas"])):
            print(f"  [{i+1}] file={meta.get('filename','?')} type={meta.get('file_type','?')}")
            print(f"       {doc[:120]}...")

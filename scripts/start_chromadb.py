"""Start ChromaDB HTTP server programmatically."""
import os
chroma_path = r"C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag\chroma"
os.environ["IS_PERSISTENT"] = "1"
os.environ["PERSIST_DIRECTORY"] = chroma_path
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_SERVER_HOST"] = "localhost"
os.environ["CHROMA_SERVER_HTTP_PORT"] = "8001"

import uvicorn
import chromadb.app as app_module

uvicorn.run(app_module.app, host="localhost", port=8001, log_level="info")

"""Dev utility — list available Groq models via the Groq API."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')
from dotenv import load_dotenv; load_dotenv()
import groq, os

client = groq.Groq(api_key=os.environ['GROQ_API_KEY'])
models = client.models.list()
for m in sorted(models.data, key=lambda x: x.id):
    print(m.id)

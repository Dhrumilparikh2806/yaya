"""Dev utility — check RAGAS baseline scores stored in query_history."""
import warnings; warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

# Check the evaluate() type check
from ragas import evaluate, aevaluate
import inspect, textwrap

src = inspect.getsource(evaluate)
# Find the type check
for i, line in enumerate(src.split('\n')):
    if 'metric' in line.lower() and ('isinstance' in line or 'type' in line or 'initialised' in line):
        print(f"L{i}: {line}")

print("---")
# What type does it check against?
from ragas.metrics import BleuScore, AspectCritic
print("BleuScore bases:", BleuScore.__bases__)
print("AspectCritic bases:", AspectCritic.__bases__)
import ragas.metrics as rm
print(dir(rm))

# Check ragas.metrics.collections metrics
from ragas.metrics.collections import Faithfulness
print("Collections Faithfulness bases:", Faithfulness.__bases__)
print("MRO:", [c.__name__ for c in Faithfulness.__mro__])

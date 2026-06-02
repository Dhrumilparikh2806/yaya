"""Queue a test task to print the actual XLSX processor code the worker sees."""
import sys
sys.path.insert(0, r'C:\Users\Dhrumil.parikh\OneDrive - Taazaa Tech Pvt Ltd\Desktop\playbook_final\geminirag')

from app.workers.celery_app import celery_app

@celery_app.task(name='debug_xlsx_limit')
def debug_xlsx_limit():
    import app.processors.xlsx_proc as m
    import inspect
    src = inspect.getsource(m.XLSXProcessor.summarise)
    for line in src.split('\n'):
        if any(x in line for x in ['1500', '500', '3000', '6000', 'truncated', '_ROW_LIMIT']):
            print(f"  CODE: {line.strip()}")
    print(f"  FILE: {m.__file__}")
    import app.processors.xlsx_proc as xlsx
    print(f"  ROW_LIMIT: {xlsx._ROW_LIMIT}")
    return "done"

result = debug_xlsx_limit.delay()
print(f"Task queued: {result.id}")
print("Check the Celery worker terminal for output...")

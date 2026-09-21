
import time, sys
sys.path.insert(0, "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle/experiments/superz_fullcycle")
from keyless_client import complete
t0 = time.time()
try:
    r = complete("llm7", [{"role": "user", "content": "Reply with the single word OK"}], max_tokens=10)
    print(f"llm7 OK in {time.time()-t0:.1f}s model={r['model']} content={r['content'][:50]!r}")
except Exception as e:
    print(f"llm7 FAIL after {time.time()-t0:.1f}s: {type(e).__name__}: {str(e)[:200]}")
t0 = time.time()
try:
    r = complete("blockrun", [{"role": "user", "content": "Reply with the single word OK"}], max_tokens=10)
    print(f"blockrun OK in {time.time()-t0:.1f}s model={r['model']} content={r['content'][:50]!r}")
except Exception as e:
    print(f"blockrun FAIL after {time.time()-t0:.1f}s: {type(e).__name__}: {str(e)[:200]}")

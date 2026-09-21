
import urllib.request, json, ssl, time
def post(url, payload, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer not-needed","api-key":"not-needed"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read().decode())
    return d["choices"][0]["message"]["content"][:120]
t0=time.time()
try:
    print("BlockRun:", post("https://blockrun.ai/api/v1/chat/completions",
        {"model":"nvidia/gpt-oss-120b","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":20,"temperature":0}), f"{time.time()-t0:.1f}s")
except Exception as e: print("BlockRun FAIL:", str(e)[:200])
t0=time.time()
try:
    print("LLM7:", post("https://api.llm7.io/v1/chat/completions",
        {"model":"fast","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":20,"temperature":0}), f"{time.time()-t0:.1f}s")
except Exception as e: print("LLM7 FAIL:", str(e)[:200])
t0=time.time()
try:
    print("Pollinations:", post("https://text.pollinations.ai/openai",
        {"model":"openai-fast","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":20,"temperature":0}), f"{time.time()-t0:.1f}s")
except Exception as e: print("Pollinations FAIL:", str(e)[:200])

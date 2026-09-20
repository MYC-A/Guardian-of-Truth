"""Minimal Ollama-compatible HTTP shim backed by z-ai-web-dev-sdk (GLM API).
Lets Google LangExtract run its genuine extraction loop (prompting, parsing,
char-offset alignment) against an API model. NOT a local model - documented.
"""
import json, os, subprocess, tempfile, hashlib, traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

BRIDGE = "/home/z/my-project/got-agentz/experiments/agentz_arch_v1/common/llm_bridge.mjs"
CACHE = "/home/z/my-project/got-agentz/experiments/agentz_arch_v1/cache"

def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl > 0:
            t = t[first_nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def call_llm(messages):
    system = ""
    user = ""
    for m in messages:
        if m.get("role") in ("system", "assistant") and not user:
            system = m.get("content", "")
        elif m.get("role") == "user":
            user = m.get("content", "")
    # provider-aware cache key (consistent with io_utils.run_llm)
    provider = "mistral" if os.environ.get("MISTRAL_API_KEY") else "zai"
    model = os.environ.get("MISTRAL_MODEL", "ministral-14b-latest") if provider == "mistral" else "glm"
    key = hashlib.sha256(json.dumps([provider, model, system, user, 2048]).encode()).hexdigest()
    p = Path(CACHE) / (key + ".json")
    if p.exists():
        return _strip_fences(json.loads(p.read_text())["content"])
    with tempfile.TemporaryDirectory() as td:
        tf, of = Path(td) / "t.json", Path(td) / "r.json"
        tf.write_text(json.dumps([{"id": "q", "system": system, "prompt": user}]))
        r = subprocess.run(["bun", BRIDGE, "--tasks", str(tf), "--out", str(of),
                        "--cache", CACHE, "--concurrency", "1"],
                       capture_output=True, text=True, timeout=300)
        if not of.exists():
            raise RuntimeError("bridge failed: " + r.stderr[-400:])
        rows = json.loads(of.read_text())
        if not rows or not rows[0].get("ok"):
            raise RuntimeError("llm error: " + str(rows[:1]))
        return _strip_fences(rows[0]["content"])

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        if "messages" in req:
            messages = req["messages"]
        else:  # /api/generate format
            messages = [{"role": "user", "content": req.get("prompt", "")}]
        try:
            content = call_llm(messages)
            if "messages" in req:
                body = {"model": req.get("model", "glm"),
                        "message": {"role": "assistant", "content": content},
                        "done": True}
            else:
                body = {"model": req.get("model", "glm"),
                        "response": content, "done": True}
            code = 200
        except Exception as e:
            body = {"error": str(e)[:300], "trace": traceback.format_exc()[-800:]}
            code = 500
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 11434), Handler).serve_forever()

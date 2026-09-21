
import requests
BASE = "http://127.0.0.1:8002/v1"
r = requests.post(f"{BASE}/chat/completions", json={
    "model": "mistral-7b-instruct-v0.3",
    "messages": [{"role": "user", "content": "Reply with exactly: LOCAL_MISTRAL_OK"}],
    "max_tokens": 15, "temperature": 0.0}, timeout=180)
print("status:", r.status_code)
print("reply:", repr(r.json()["choices"][0]["message"]["content"][:80]))
r2 = requests.get(f"{BASE}/models", timeout=20)
print("models:", r2.status_code)

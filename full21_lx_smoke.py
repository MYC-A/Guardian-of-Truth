#!/usr/bin/env python3
"""Smoke: local mistral-7b chat completion + langextract API probe."""
import json
import requests

BASE = "http://127.0.0.1:8001/v1"

# 1. chat completion smoke
r = requests.post(f"{BASE}/chat/completions", json={
    "model": "mistral-7b-instruct-v0.3",
    "messages": [{"role": "user", "content": "Reply with exactly: LOCAL_MISTRAL_OK"}],
    "max_tokens": 20, "temperature": 0.0,
}, timeout=120)
print("chat status:", r.status_code)
data = r.json()
print("reply:", data["choices"][0]["message"]["content"][:100])
print("usage:", data.get("usage", {}).get("completion_tokens"))

# 2. langextract API probe
import langextract as lx
from langextract.providers.openai import OpenAILanguageModel
print("lx version:", getattr(lx, "__version__", "?"))
print("extract sig:", lx.extract.__doc__[:400] if lx.extract.__doc__ else "no doc")
import inspect
try:
    print(inspect.signature(lx.extract))
except Exception as e:
    print("sig err:", e)
print("ExampleData:", lx.data.ExampleData)
print("Extraction:", lx.data.Extraction)
print("OpenAILanguageModel:", OpenAILanguageModel)
try:
    print(inspect.signature(OpenAILanguageModel.__init__))
except Exception as e:
    print("om sig err:", e)

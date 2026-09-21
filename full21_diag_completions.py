#!/usr/bin/env python3
"""Diagnose: completions endpoint with manual INST formatting + process check."""
import json
import requests

BASE = "http://127.0.0.1:8001/v1"

# 1. raw completions with manual formatting
r = requests.post(f"{BASE}/completions", json={
    "model": "mistral-7b-instruct-v0.3",
    "prompt": "<s>[INST] Reply with exactly: LOCAL_MISTRAL_OK [/INST]",
    "max_tokens": 15, "temperature": 0.0,
}, timeout=120)
print("completions status:", r.status_code)
if r.status_code == 200:
    print("reply:", repr(r.json()["choices"][0]["text"][:80]))
else:
    print("err:", r.text[:300])

# 2. chat endpoint again
r2 = requests.post(f"{BASE}/chat/completions", json={
    "model": "mistral-7b-instruct-v0.3",
    "messages": [{"role": "user", "content": "Say OK"}],
    "max_tokens": 10, "temperature": 0.0,
}, timeout=120)
print("chat reply:", repr(r2.json()["choices"][0]["message"]["content"][:80]))

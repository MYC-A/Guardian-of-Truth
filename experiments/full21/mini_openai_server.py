#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for local Mistral-7B-Instruct-v0.3 (FULL_21).

Endpoints: GET /v1/models, POST /v1/chat/completions, POST /v1/completions.
Sequential generation (thread lock), bf16, transformers backend. This server
exists because the host vLLM build is incompatible with the venv torch and
produces corrupt generations (verified: direct transformers generation is
correct, vLLM output is garbage).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_PATH = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3"
MODEL_NAME = "mistral-7b-instruct-v0.3"
PORT = int(os.environ.get("MINI_SERVER_PORT", "8002"))

app = FastAPI()
_lock = threading.Lock()

print("loading tokenizer...", flush=True)
tok = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
print("loading model...", flush=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH, local_files_only=True, torch_dtype=torch.bfloat16, device_map="auto")
model.eval()
print("model ready", flush=True)


class Msg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    model: str = MODEL_NAME
    messages: List[Msg]
    max_tokens: int = 1024
    temperature: float = 0.0
    top_p: float = 1.0
    stream: bool = False


class CompReq(BaseModel):
    model: str = MODEL_NAME
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.0
    echo: bool = False


def gen_ids(ids, max_tokens, temperature):
    with _lock:
        t0 = time.perf_counter()
        do_sample = temperature > 0
        with torch.inference_mode():
            out = model.generate(
                ids, do_sample=do_sample,
                temperature=max(temperature, 1e-5) if do_sample else None,
                top_p=None if not do_sample else 0.95,
                max_new_tokens=max_tokens,
                pad_token_id=tok.eos_token_id)
        dt = time.perf_counter() - t0
    new = out[0][ids.shape[-1]:]
    n_in, n_out = int(ids.shape[-1]), int(new.shape[-1])
    return tok.decode(new, skip_special_tokens=True), n_in, n_out, dt


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model",
            "created": int(time.time()), "owned_by": "local",
            "max_model_len": 16384}]}


def flatten_messages(messages):
    """Merge system messages into the first user message (Mistral v0.3 template
    supports only user/assistant alternating)."""
    out = []
    pending_system = []
    for m in messages:
        role, content = m.get("role"), m.get("content") or ""
        if role == "system":
            pending_system.append(content.strip())
            continue
        if role not in ("user", "assistant"):
            content = f"[{role}] {content}"
            role = "user" if not out or out[-1]["role"] == "assistant" else "assistant"
        if role == "user" and pending_system:
            content = "\n\n".join(pending_system + [content])
            pending_system = []
        out.append({"role": role, "content": content})
    if pending_system:
        out.append({"role": "user", "content": "\n\n".join(pending_system)})
    return out


@app.post("/v1/chat/completions")
def chat(req: ChatReq):
    messages = flatten_messages([m.dict() for m in req.messages])
    try:
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    except Exception:
        # fallback: single-turn manual formatting (safe for any role sequence)
        sys_txt = "\n\n".join(m["content"] for m in messages if m["role"] != "assistant")
        asst_prefix = "".join(f" {m['content']}</s>" for m in messages if m["role"] == "assistant")
        prompt = f"<s>[INST] {sys_txt} [/INST]{asst_prefix}"
    ids = tok.encode(prompt, add_special_tokens=False, return_tensors="pt").to(model.device)
    text, n_in, n_out, dt = gen_ids(ids, req.max_tokens, req.temperature)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
        "created": int(time.time()), "model": MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
        "_latency_s": round(dt, 2),
    }


@app.post("/v1/completions")
def completions(req: CompReq):
    ids = tok.encode(req.prompt, add_special_tokens=False, return_tensors="pt").to(model.device)
    text, n_in, n_out, dt = gen_ids(ids, req.max_tokens, req.temperature)
    return {
        "id": f"cmpl-{uuid.uuid4().hex[:12]}", "object": "text_completion",
        "created": int(time.time()), "model": MODEL_NAME,
        "choices": [{"index": 0, "text": text, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
    }


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")

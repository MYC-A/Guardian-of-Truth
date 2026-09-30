#!/usr/bin/env python3
"""Shared LLM client for System Research V2 (repo-side).

OpenAI-compatible multi-provider client:
- sha-keyed disk cache OUTSIDE the repo (deterministic replay, §100 economy)
- retry with backoff on 429/5xx/timeouts
- JSON-object response mode with tolerant parsing
- per-call cost log (§99): provider/model/calls/tokens/wall
No API key value is ever printed or written inside the repo.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from openai import OpenAI

HERE = Path(__file__).resolve().parent
EXTERNAL = Path("/home/z/my-project/srv2-research")
CACHE_DIR = EXTERNAL / "llm_cache"
COST_LOG = HERE / "outputs" / "cost_log.jsonl"

_LOCK = None


def _thread_lock():
    global _LOCK
    import threading
    if _LOCK is None:
        _LOCK = threading.Lock()
    return _LOCK


def _load_env() -> dict:
    env: dict[str, str] = {}
    with open(EXTERNAL / "api_keys.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                k, v = line[len("export "):].split("=", 1)
                env[k] = v.strip().strip('"')
    return env


_ENV = _load_env()
PROVIDERS = {
    "ollama": ("https://ollama.com/v1", _ENV.get("OLLAMA_API_KEY", "")),
    "ukisai": ("https://ukisai.com/api/swift/v1", _ENV.get("UKISAI_API_KEY", "")),
    "vireonix": ("https://vireonix.ai/v1", _ENV.get("VIREONIX_API_KEY", "")),
}
MODELS = {
    "gemma4:31b": "ollama",
    "gpt-oss:20b": "ollama",
    "gpt-oss:120b": "ollama",
    "nemotron-3-nano:30b": "ollama",
    "nemotron-3-super": "ollama",
    "nemotron-3-ultra": "ollama",
    "swift": "ukisai",
    "auto": "vireonix",
}

_clients: dict[str, OpenAI] = {}


def _client(provider: str) -> OpenAI:
    if provider not in _clients:
        base, key = PROVIDERS[provider]
        _clients[provider] = OpenAI(base_url=base, api_key=key, timeout=240.0)
    return _clients[provider]


def _cache_key(provider: str, model: str, messages: list, **kw) -> str:
    blob = json.dumps(
        {"p": provider, "m": model, "msgs": messages, **kw},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _log_cost(entry: dict) -> None:
    COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    lock = _thread_lock()
    with lock:
        with open(COST_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")




def _extract_json(content: str):
    """Tolerant JSON extraction: fence-strip, substring, trailing commas."""
    txt = (content or "").strip()
    if txt.startswith("```"):
        first_nl = txt.find("\n")
        if first_nl != -1:
            txt = txt[first_nl + 1:]
        if txt.rstrip().endswith("```"):
            txt = txt.rstrip()[:-3].rstrip()
    try:
        return json.loads(txt)
    except Exception:
        pass
    if "{" in txt and "}" in txt:
        sub = txt[txt.index("{"):txt.rindex("}") + 1]
        try:
            return json.loads(sub)
        except Exception:
            repaired = re.sub(r",[ \t]*\n?[ \t]*([}\]])", r"\n\1", sub)
            try:
                return json.loads(repaired)
            except Exception:
                return None
    return None


def chat(model: str, messages: list, *, max_tokens: int = 4000,
         temperature: float = 0.0, json_mode: bool = True,
         use_cache: bool = True, max_retries: int = 4) -> dict:
    """Return {content, parsed?, usage, latency_s, cached, model, provider}."""
    if model not in MODELS:
        raise KeyError(f"unknown model {model}")
    provider = MODELS[model]
    key = _cache_key(provider, model, messages, max_tokens=max_tokens,
                     temperature=temperature, json_mode=json_mode)
    cache_file = CACHE_DIR / f"{key[:2]}/{key}.json"
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        cached["cached"] = True
        if json_mode:
            cached["parsed"] = _extract_json(cached.get("content") or "")
        return cached

    last_err = None
    for attempt in range(max_retries):
        t0 = time.time()
        try:
            kwargs = dict(model=model, messages=messages,
                          max_tokens=max_tokens, temperature=temperature)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            r = _client(provider).chat.completions.create(**kwargs)
            content = r.choices[0].message.content or ""
            parsed = _extract_json(content) if json_mode else None
            out = {
                "content": content,
                "parsed": parsed,
                "usage": ({"in": r.usage.prompt_tokens,
                           "out": r.usage.completion_tokens} if r.usage else None),
                "latency_s": round(time.time() - t0, 3),
                "cached": False,
                "model": model, "provider": provider,
            }
            if use_cache:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(out, ensure_ascii=False),
                                      encoding="utf-8")
            _log_cost({"model": model, "provider": provider,
                       "in": (out["usage"] or {}).get("in"),
                       "out": (out["usage"] or {}).get("out"),
                       "latency_s": out["latency_s"], "cached": False,
                       "ts": time.time()})
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(min(2 ** attempt * 2, 30))
    raise RuntimeError(f"model {model} failed after {max_retries} retries: {last_err}")


def cost_summary() -> dict:
    if not COST_LOG.exists():
        return {"calls": 0}
    calls = 0
    by_model: dict[str, int] = {}
    tokens_in = tokens_out = 0
    latency = 0.0
    with open(COST_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("cached"):
                continue
            calls += 1
            by_model[e["model"]] = by_model.get(e["model"], 0) + 1
            tokens_in += e.get("in") or 0
            tokens_out += e.get("out") or 0
            latency += e.get("latency_s") or 0.0
    return {"calls": calls, "by_model": by_model,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "wall_s": round(latency, 1)}

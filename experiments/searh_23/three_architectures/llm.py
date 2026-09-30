#!/usr/bin/env python3
"""Multi-provider LLM client for the three-architectures experiment.

Providers (all smoke-tested 2026-09-30, statuses in ENVIRONMENT.md):
  mistral   api.mistral.ai            (key: secrets/mistral.env)
  ollama    ollama.com/v1            (free; gemma4:31b, gpt-oss:20b/120b,
                                       nemotron-3-nano:30b/-super/-ultra)
  ukisai    ukisai.com/api/swift/v1  (free; model "swift", reasoning)
  vireonix  vireonix.ai/v1           (free; model "auto" — family
                                       UNVERIFIABLE: never counted as an
                                       independent family)

Discipline (directive §2/§9):
  * keys read from secret files; NEVER printed, never written into the repo
  * sha-keyed disk cache OUTSIDE the repo (deterministic replay)
  * bounded retries with backoff on 429/5xx/timeout (transport level only)
  * one technical re-ask for invalid JSON happens at the CALLER level
  * cost log per call: provider/model/usage/tokens/wall
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from openai import OpenAI

BASE = Path("/workspace/guardian")
SECRETS = BASE / "secrets"
CACHE_DIR = BASE / "results" / "ta_llm_cache"
COST_LOG = BASE / "results" / "ta_cost_log.jsonl"

_LOCK = threading.Lock()


def _load_env_file(p: Path) -> dict:
    env: dict[str, str] = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                k, v = line[len("export "):].split("=", 1)
                env[k] = v.strip().strip('"')
    return env


_ENV = {}
_ENV.update(_load_env_file(SECRETS / "mistral.env"))
_ENV.update(_load_env_file(SECRETS / "api_keys.env"))

PROVIDERS = {
    "mistral": ("https://api.mistral.ai/v1", _ENV.get("MISTRAL_API_KEY", "")),
    "ollama": ("https://ollama.com/v1", _ENV.get("OLLAMA_API_KEY", "")),
    "ukisai": ("https://ukisai.com/api/swift/v1",
               _ENV.get("UKISAI_API_KEY", "none")),
    "vireonix": ("https://vireonix.ai/v1",
                 _ENV.get("VIREONIX_API_KEY", "unused")),
}
# default mistral model from env file if present
DEFAULT_MISTRAL_MODEL = _ENV.get("MISTRAL_MODEL", "ministral-14b-latest")

MODEL_REGISTRY = {
    # strong local-ish free API models (ollama.com)
    "gemma4:31b": "ollama",
    "gpt-oss:20b": "ollama",
    "gpt-oss:120b": "ollama",
    "nemotron-3-nano:30b": "ollama",
    "nemotron-3-super": "ollama",
    "nemotron-3-ultra": "ollama",
    # other families
    "swift": "ukisai",
    "auto": "vireonix",
    # mistral family
    DEFAULT_MISTRAL_MODEL: "mistral",
}

_clients: dict[str, OpenAI] = {}


def _client(model: str) -> tuple[str, OpenAI]:
    provider = MODEL_REGISTRY.get(model)
    if provider is None:
        # unknown model: allow explicit "provider/model" syntax
        if "/" in model:
            provider, model = model.split("/", 1)
        else:
            raise ValueError(f"model '{model}' not in registry; "
                             f"use 'provider/model'")
    if provider not in _clients:
        base, key = PROVIDERS[provider]
        _clients[provider] = OpenAI(base_url=base, api_key=key, timeout=240.0)
    return model, _clients[provider]


# ------------------------------------------------------------------- cache

def _cache_key(model: str, messages: list, **kw) -> str:
    blob = json.dumps({"m": model, "msgs": messages, **kw},
                      sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / key[:2] / f"{key}.json"


def _cache_get(key: str):
    p = _cache_path(key)
    if p.exists():
        try:
            return json.loads(p.read_text()), True
        except Exception:
            return None, False
    return None, False


def _cache_put(key: str, payload: dict) -> None:
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, p)


# ------------------------------------------------------------------- cost

def _log_cost(entry: dict) -> None:
    COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(COST_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------- json

def extract_json(content: str):
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
        sub = txt[txt.index("{"): txt.rindex("}") + 1]
        try:
            return json.loads(sub)
        except Exception:
            repaired = re.sub(r",[ \t]*\n?[ \t]*([}\]])", r"\n\1", sub)
            try:
                return json.loads(repaired)
            except Exception:
                return None
    return None


# ------------------------------------------------------------------- chat

RETRYABLE = (429, 500, 502, 503, 504)


def chat(model: str, messages: list, *, max_tokens: int = 4000,
         temperature: float = 0.0, json_mode: bool = True,
         seed: int | None = None, top_p: float | None = None,
         use_cache: bool = True, transport_retries: int = 3,
         caller: str = "") -> dict:
    """One chat call. Returns {content, usage, cached, model, elapsed}.

    Transport retries (429/5xx/timeout) are bounded and counted in cost.
    Invalid-JSON re-asks are NOT done here (caller-level, directive §9).
    Sampling params only apply on live calls; cache hits replay exactly
    (cache key includes them).
    """
    m, provider_model = model, model
    kw = {"max_tokens": max_tokens, "temperature": temperature,
          "json_mode": json_mode}
    if seed is not None:
        kw["seed"] = seed
    if top_p is not None:
        kw["top_p"] = top_p
    key = _cache_key(model, messages, **kw)
    if use_cache:
        hit, _ = _cache_get(key)
        if hit is not None:
            hit["cached"] = True
            return hit

    model_r, client = _client(model)
    t0 = time.time()
    last_err = None
    for attempt in range(transport_retries + 1):
        try:
            kwargs = dict(model=model_r, messages=messages,
                          max_tokens=max_tokens, temperature=temperature)
            if seed is not None:
                kwargs["seed"] = seed
            if top_p is not None:
                kwargs["top_p"] = top_p
            if json_mode and provider_family(model_r) != "ukisai":
                # swift (ukisai) rejected response_format in smoke tests
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            u = {}
            if usage is not None:
                for k in ("prompt_tokens", "completion_tokens",
                          "total_tokens"):
                    u[k] = getattr(usage, k, None)
            elapsed = round(time.time() - t0, 3)
            payload = {"content": content, "usage": u, "cached": False,
                       "model": model_r, "elapsed": elapsed}
            _cache_put(key, payload)
            _log_cost({"ts": time.time(), "caller": caller, "model": model_r,
                       "provider": PROVIDERS[_provider_of(model_r)][0],
                       "prompt_tokens": u.get("prompt_tokens"),
                       "completion_tokens": u.get("completion_tokens"),
                       "elapsed": elapsed, "attempt": attempt,
                       "cached_write": True})
            return payload
        except Exception as e:  # transport-level
            last_err = e
            status = getattr(e, "status_code", None)
            if status not in RETRYABLE and "timeout" not in str(e).lower():
                break
            time.sleep(min(2 ** attempt * 2, 30))
    _log_cost({"ts": time.time(), "caller": caller, "model": model_r,
               "error": str(last_err)[:200], "transport_fail": True})
    return {"content": None, "usage": {}, "cached": False, "model": model_r,
            "elapsed": round(time.time() - t0, 3),
            "error": str(last_err)}


def provider_family(model: str) -> str:
    """Family label for vote diversity accounting. vireonix 'auto' family
    is UNVERIFIABLE and must never be counted as an independent family."""
    if model in ("swift",):
        return "swift"
    if model == "auto":
        return "vireonix-auto-unknown"
    if model.startswith("gpt-oss"):
        return "gpt-oss"
    if model.startswith("gemma"):
        return "gemma"
    if model.startswith("nemotron"):
        return "nemotron"
    if model.startswith(("mistral", "ministral", "codestral")):
        return "mistral"
    return model


def _provider_of(model: str) -> str:
    return MODEL_REGISTRY.get(model, "unknown")


def available() -> dict:
    """Which channels have a key configured (booleans only, no values)."""
    out = {}
    for p, (_, key) in PROVIDERS.items():
        out[p] = bool(key) or p in ("ukisai", "vireonix")
    return out

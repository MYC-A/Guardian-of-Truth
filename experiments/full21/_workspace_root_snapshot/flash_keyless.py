#!/usr/bin/env python3
"""flash-keyless: minimal OpenAI-compatible keyless client (prefix: flash).

Providers (per directive §19.3, verified in earlier smoke tests):
  blockrun     https://blockrun.ai/api/v1          nvidia/gpt-oss-120b (pool-substituted)
  pollinations https://text.pollinations.ai/openai  openai-fast (gpt-oss-20b)
  llm7         https://api.llm7.io/v1              "default"/"fast" selector

Features: per-provider min-interval rate limiting, retries, disk cache,
tolerant JSON object extraction. complete() returns the text plus a
"_served_model" marker inside a dict wrapper when available.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

PROVIDERS: dict[str, dict[str, Any]] = {
    "blockrun": {
        "base_url": "https://blockrun.ai/api/v1",
        "model": "nvidia/gpt-oss-120b",
        "api_key": "not-needed",
        "min_interval": 13.0,
        "timeout": 240,
    },
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "model": "openai-fast",
        "api_key": "not-needed",
        "min_interval": 16.0,
        "timeout": 240,
    },
    "llm7": {
        "base_url": "https://api.llm7.io/v1",
        "model": "fast",
        "api_key": "unused",
        "min_interval": 8.0,
        "timeout": 240,
    },
}

_last_call: dict[str, float] = {}
_last_served: dict[str, str | None] = {}
_cache_root = Path("/mnt/data/guardian/agent-workspace/flash-repo/outputs/flash/_llm_cache_flash")


def _cache_path(provider: str, model: str, messages: list[dict], params: dict) -> Path:
    blob = json.dumps({"p": provider, "m": model, "msgs": messages, "params": params},
                      ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return _cache_root / provider / f"{h}.json"


def extract_json_object(text: str) -> dict[str, Any]:
    """Tolerant extraction of the first JSON object from a model reply."""
    if not text:
        raise ValueError("empty model reply")
    cleaned = text.strip()
    fence = re.match(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("unbalanced JSON object in reply")
    obj = json.loads(cleaned[start:end])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


def complete(provider: str, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 400, retries: int = 2) -> str:
    cfg = PROVIDERS[provider]
    model = cfg["model"]
    cp = _cache_path(provider, model, messages,
                     {"temperature": temperature, "max_tokens": max_tokens})
    if cp.is_file():
        try:
            return json.loads(cp.read_text(encoding="utf-8")).get("text", "")
        except Exception:  # noqa: BLE001
            pass
    wait = cfg["min_interval"] - (time.time() - _last_call.get(provider, 0.0))
    if wait > 0:
        time.sleep(wait)
    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"],
                            timeout=cfg["timeout"])
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens)
            _last_call[provider] = time.time()
            text = resp.choices[0].message.content or ""
            served = getattr(resp, "model", None)
            _last_served[provider] = served
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps({"text": text, "served_model": served},
                                     ensure_ascii=False), encoding="utf-8")
            return text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(4)
    raise RuntimeError(f"{provider} completion failed: {last_err}")

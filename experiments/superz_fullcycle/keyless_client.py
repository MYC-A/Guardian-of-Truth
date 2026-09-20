#!/usr/bin/env python3
"""Keyless LLM client for the SuperZ full-cycle research line.

OpenAI-compatible providers reachable from the ModelScope server without keys:

  J1 llm7       https://api.llm7.io/v1      model "default" (resolves e.g. minimax-m2.7)  ~10 RPM
  J2 pollutions https://text.pollinations.ai/openai  model "openai-fast" (gpt-oss-20b)   ~1 req / 15 s
  J3 blockrun   https://blockrun.ai/api/v1  model "nvidia/gpt-oss-120b" (pool-substituted) limits unknown

Features: per-provider rate limiting, retries with backoff, disk cache keyed by
(provider, model, messages, params), tolerant JSON extraction (code fences,
balanced-scan, // comments, trailing commas). Cache dir is per-experiment.
The caller records the ACTUAL responded model identity for provenance.
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
    "llm7": {
        "base_url": "https://api.llm7.io/v1",
        "model": "default",
        "api_key": "unused",
        "min_interval": 8.0,
        "timeout": 180,
    },
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "model": "openai-fast",
        "api_key": "not-needed",
        "min_interval": 16.0,
        "timeout": 180,
    },
    "blockrun": {
        "base_url": "https://blockrun.ai/api/v1",
        "model": "nvidia/gpt-oss-120b",
        "api_key": "not-needed",
        "min_interval": 13.0,
        "timeout": 180,
    },
}

_last_call: dict[str, float] = {}


class KeylessError(RuntimeError):
    pass


def _cache_key(provider: str, model: str, messages: list[dict], params: dict) -> str:
    blob = json.dumps({"p": provider, "m": model, "msgs": messages, "params": params},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def extract_json_object(text: str) -> dict[str, Any]:
    """Tolerant extraction of the first JSON object from a model reply."""
    if not text:
        raise KeylessError("empty model reply")
    cleaned = text.strip()
    # strip code fences
    fence = re.match(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # locate first '{' and balanced-scan
    start = cleaned.find("{")
    if start < 0:
        raise KeylessError("no JSON object in reply")
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
        raise KeylessError("unbalanced JSON object in reply")
    blob = cleaned[start:end]
    # strip // comments outside strings and trailing commas
    out = []
    in_str = False
    esc = False
    i = 0
    while i < len(blob):
        ch = blob[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch == "/" and i + 1 < len(blob) and blob[i + 1] == "/":
            while i < len(blob) and blob[i] != "\n":
                i += 1
            continue
        else:
            out.append(ch)
        i += 1
    blob2 = "".join(out)
    blob2 = re.sub(r",\s*([}\]])", r"\1", blob2)
    try:
        value = json.loads(blob2)
    except json.JSONDecodeError as e:
        raise KeylessError(f"JSON decode failed: {e}") from e
    if not isinstance(value, dict):
        raise KeylessError("reply is not a JSON object")
    return value


def complete(provider: str, messages: list[dict], *, max_tokens: int = 1024,
             temperature: float = 0.0, cache_dir: Path | None = None,
             use_cache: bool = True, max_attempts: int = 4) -> dict[str, Any]:
    """One chat completion. Returns {content, model, usage, cached, latency}."""
    spec = PROVIDERS[provider]
    model = spec["model"]
    params = {"max_tokens": max_tokens, "temperature": temperature}

    ck = None
    if cache_dir is not None and use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        ck = cache_dir / (_cache_key(provider, model, messages, params) + ".json")
        if ck.is_file():
            try:
                cached = json.loads(ck.read_text(encoding="utf-8"))
                cached["cached"] = True
                return cached
            except Exception:
                pass

    client = OpenAI(base_url=spec["base_url"], api_key=spec["api_key"],
                    timeout=spec["timeout"])
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        # provider rate limiting
        now = time.monotonic()
        wait = _last_call.get(provider, 0.0) + spec["min_interval"] - now
        if wait > 0:
            time.sleep(wait)
        _last_call[provider] = time.monotonic()
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature)
            content = resp.choices[0].message.content or ""
            result = {
                "content": content,
                "model": getattr(resp, "model", None) or model,
                "usage": (resp.usage.model_dump() if resp.usage else None),
                "cached": False,
                "latency": round(time.monotonic() - t0, 3),
                "provider": provider,
                "attempts": attempt + 1,
            }
            if ck is not None:
                ck.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
        except Exception as e:  # 429 / 5xx / timeout / empty
            last_err = e
            time.sleep(min(2 ** attempt * 5, 40))
    raise KeylessError(f"{provider}: all {max_attempts} attempts failed: {last_err}")

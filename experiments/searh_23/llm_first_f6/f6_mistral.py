"""F6 local Mistral client — byte-compatible request semantics with the
frozen pl_common.Mistral (temperature 0, json_object response format,
sha-keyed disk cache, 429 retry ladder, usage accounting), adapted to
read credentials from the local guardian-access env file.

The API key is NEVER printed or written into outputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path("/home/z/my-project/guardian-access/mistral.env")


def mistral_settings() -> dict:
    saved = {}
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"MISTRAL_API_KEY", "MISTRAL_MODEL"}:
                saved[key.strip()] = value.strip().strip("\"'")
    return {"MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY") or saved.get("MISTRAL_API_KEY", ""),
            "MISTRAL_MODEL": os.environ.get("MISTRAL_MODEL") or saved.get("MISTRAL_MODEL", "ministral-14b-latest")}


class Mistral:
    """Minimal cached chat client for api.mistral.ai, temperature 0."""

    def __init__(self, model: str | None = None, cache_dir: Path | None = None):
        cfg = mistral_settings()
        self.key = cfg["MISTRAL_API_KEY"]
        if not self.key:
            raise RuntimeError("MISTRAL_API_KEY missing")
        self.model = model or cfg["MISTRAL_MODEL"]
        self.cache_dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.next_call = 0.0
        self.calls = 0
        self.throttled = 0
        self.usage_total = {"prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0}

    def _cache_path(self, system: str, user: str, max_tokens: int) -> Path:
        blob = json.dumps({"m": self.model, "s": system, "u": user,
                           "t": max_tokens}, ensure_ascii=False, sort_keys=True)
        return self.cache_dir / (hashlib.sha256(blob.encode()).hexdigest() + ".json")

    def ask(self, system: str, user: str, max_tokens: int = 1500,
            use_cache: bool = True) -> dict:
        ck = self._cache_path(system, user, max_tokens) if self.cache_dir else None
        if use_cache and ck is not None and ck.is_file():
            rec = json.loads(ck.read_text(encoding="utf-8"))
            rec["cached"] = True
            return rec
        payload = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        body = None
        rate_wait = 20.0
        t0 = time.monotonic()
        for attempt in range(14):
            if self.next_call > time.monotonic():
                time.sleep(self.next_call - time.monotonic())
            self.next_call = time.monotonic() + 3.0
            request = urllib.request.Request(
                "https://api.mistral.ai/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Authorization": "Bearer " + self.key,
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    self.throttled += 1
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else rate_wait
                    except ValueError:
                        wait = rate_wait
                    wait = min(180.0, max(15.0, wait))
                    rate_wait = min(120.0, rate_wait * 1.5)
                    time.sleep(wait)
                    continue
                detail = exc.read(800).decode("utf-8", "replace")
                raise RuntimeError(f"Mistral HTTP {exc.code}: {detail}") from None
            except Exception:
                if attempt >= 13:
                    raise
                time.sleep(5)
        latency = round(time.monotonic() - t0, 3)
        choice = body["choices"][0]
        raw = choice["message"].get("content") or ""
        usage = body.get("usage", {}) or {}
        for k in self.usage_total:
            self.usage_total[k] += int(usage.get(k, 0) or 0)
        self.calls += 1
        rec = {"raw": raw, "finish_reason": choice.get("finish_reason"),
               "served_model": body.get("model", self.model),
               "usage": usage, "latency": latency, "cached": False}
        if ck is not None:
            ck.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return rec

    @staticmethod
    def parse_json(raw: str) -> tuple[dict, str]:
        """Tolerant JSON object extraction; returns ({}, error) on failure."""
        if not raw:
            return {}, "empty"
        cleaned = raw.strip()
        fence = re.match(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()
        start = cleaned.find("{")
        if start < 0:
            return {}, "no_json_object"
        depth = 0
        in_str = esc = False
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
            return {}, "unbalanced"
        try:
            obj = json.loads(cleaned[start:end])
        except Exception as exc:
            return {}, f"json_error: {exc}"
        if not isinstance(obj, dict):
            return {}, "not_an_object"
        return obj, ""

"""z-ai LLM client bridge with disk caching.

Calls the local `z-ai chat` CLI (model: glm-4-plus) via subprocess.
Every request is cached on disk by SHA256(model, system, user, thinking)
so runs are resumable and reproducible. Cache lives outside git in
/tmp-free persistent location: experiments/superz_v1/results/llm_cache/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE.parent / "results" / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BRIDGE = HERE / "zai_bridge.mjs"
TMP_DIR = HERE.parent / "results" / ".bridge_tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = 600  # seconds per call
MAX_RETRIES = 5
_seq = 0
import threading
_pace_lock = threading.Lock()
_last_call_ts = [0.0]
MIN_CALL_INTERVAL_S = 1.5  # gentle pacing to avoid 429

# --- providers ---
PROVIDER_ZAI = "zai"
PROVIDER_MISTRAL = "mistral"
_MISTRAL_KEY = None
_MISTRAL_MODEL = "ministral-14b-latest"


def _mistral_key() -> str:
    global _MISTRAL_KEY
    if _MISTRAL_KEY is None:
        env = Path(__file__).resolve().parents[1] / ".secrets" / "mistral.env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("MISTRAL_API_KEY="):
                    _MISTRAL_KEY = line.split('"')[1]
                    break
        if not _MISTRAL_KEY:
            _MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "")
    return _MISTRAL_KEY


def _mistral_chat(user: str, system: str, timeout: float) -> tuple[bool, str, str, str]:
    """Direct HTTPS call to Mistral. Returns (ok, content, model, error)."""
    import urllib.request
    import urllib.error

    payload = {
        "model": _MISTRAL_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {_mistral_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            obj = json.loads(r.read())
        content = (obj["choices"][0]["message"].get("content") or "").strip()
        if not content:
            return False, "", obj.get("model", ""), "empty-content"
        return True, content, obj.get("model", ""), ""
    except urllib.error.HTTPError as e:
        body = e.read()[:200]
        return False, "", "", f"http-{e.code}: {body!r}"
    except Exception as e:  # noqa: BLE001
        return False, "", "", f"{type(e).__name__}: {e}"


@dataclass
class LLMResponse:
    ok: bool
    content: str
    error: str = ""
    cached: bool = False
    elapsed_s: float = 0.0
    model: str = ""
    attempts: int = 0


def _key(system: str, user: str, thinking: bool, provider: str = PROVIDER_ZAI) -> str:
    h = hashlib.sha256()
    for part in (provider, "\x00<P>\x00", system, "\x00<SEP>\x00", user, str(thinking)):
        h.update(part.encode("utf-8", "replace"))
    return h.hexdigest()


def chat(
    user: str,
    system: str = "You are a precise assistant.",
    thinking: bool = False,
    use_cache: bool = True,
    max_retries: int = MAX_RETRIES,
    tag: str = "",
    provider: str = PROVIDER_ZAI,
) -> LLMResponse:
    """Single chat completion (z-ai GLM or Mistral), cached."""
    global _seq
    with _pace_lock:
        wait = _last_call_ts[0] + MIN_CALL_INTERVAL_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call_ts[0] = time.time()
        _seq += 1
        my_seq = _seq
    key = _key(system, user, thinking, provider)
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        try:
            rec = json.loads(cache_file.read_text(encoding="utf-8"))
            return LLMResponse(
                ok=True,
                content=rec["content"],
                cached=True,
                elapsed_s=0.0,
                model=rec.get("model", ""),
                attempts=0,
            )
        except (json.JSONDecodeError, KeyError):
            pass  # fall through to live call

    last_err = ""
    t0 = time.time()
    rate_limit_hits = 0
    for attempt in range(1, max_retries + 1):
        if provider == PROVIDER_MISTRAL:
            try:
                ok, content, model, err = _mistral_chat(user, system, DEFAULT_TIMEOUT)
                if ok:
                    cache_file.write_text(
                        json.dumps(
                            {
                                "content": content,
                                "model": model,
                                "tag": tag,
                                "system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
                                "ts": time.time(),
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    return LLMResponse(
                        ok=True, content=content, cached=False,
                        elapsed_s=time.time() - t0, model=model, attempts=attempt,
                    )
                last_err = err
                if "429" in err or "rate" in err.lower():
                    rate_limit_hits += 1
                    if attempt < max_retries:
                        time.sleep(min(30 * rate_limit_hits, 150))
                        continue
            except Exception as e:  # noqa: BLE001
                last_err = f"mistral-error: {e}"
            if attempt < max_retries:
                time.sleep(5 * attempt)
            continue
        req_f = TMP_DIR / f"req_{os.getpid()}_{my_seq}_{attempt}.json"
        resp_f = TMP_DIR / f"resp_{os.getpid()}_{my_seq}_{attempt}.json"
        try:
            req_f.write_text(
                json.dumps({"system": system, "user": user, "thinking": thinking},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["node", str(BRIDGE), str(req_f), str(resp_f)],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
            )
            if resp_f.exists():
                out = json.loads(resp_f.read_text(encoding="utf-8"))
                if out.get("ok") and out.get("content", "").strip():
                    content = out["content"]
                    model = out.get("model", "")
                    cache_file.write_text(
                        json.dumps(
                            {
                                "content": content,
                                "model": model,
                                "tag": tag,
                                "system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
                                "ts": time.time(),
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    return LLMResponse(
                        ok=True, content=content, cached=False,
                        elapsed_s=time.time() - t0, model=model, attempts=attempt,
                    )
                err = out.get("error", "bridge-unknown")
                # rate limit: wait longer, do not burn retries quickly
                if "429" in str(err) or "Too many" in str(err) or "rate" in str(err).lower():
                    rate_limit_hits += 1
                    wait = min(30 * rate_limit_hits, 120)
                    last_err = f"rate-limit: {str(err)[:200]}"
                    if attempt < max_retries:
                        time.sleep(wait)
                        continue
                last_err = str(err)[:300]
            else:
                last_err = f"no-response-file exit={proc.returncode} err={proc.stderr[:200]!r}"
        except subprocess.TimeoutExpired:
            last_err = "timeout"
        except (OSError, json.JSONDecodeError) as e:
            last_err = f"os-error: {e}"
        finally:
            for f in (req_f, resp_f):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
        if attempt < max_retries:
            time.sleep(5 * attempt)
    return LLMResponse(ok=False, content="", error=last_err, attempts=max_retries)


def chat_batch(
    requests: list[dict],
    workers: int = 3,
    **common_kwargs,
) -> list[LLMResponse]:
    """Parallel batch of chat() calls using a thread pool."""
    import concurrent.futures

    def _one(req: dict) -> LLMResponse:
        kwargs = {**common_kwargs, **req}
        return chat(**kwargs)

    results: list[Optional[LLMResponse]] = [None] * len(requests)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, r): i for i, r in enumerate(requests)}
        for fut in concurrent.futures.as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[idx] = LLMResponse(ok=False, content="", error=f"batch-error: {e}")
    return [r if r is not None else LLMResponse(ok=False, content="", error="missing") for r in results]


def extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from an LLM reply (handles ```json fences)."""
    text = text.strip()
    # strip code fences
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    # direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # first {...} balanced scan
    start = text.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None

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
CACHE_DIR = HERE.parents[1] / "results" / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BRIDGE = HERE / "zai_bridge.mjs"
TMP_DIR = HERE.parents[1] / "results" / ".bridge_tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = 600  # seconds per call
MAX_RETRIES = 3
_seq = 0


@dataclass
class LLMResponse:
    ok: bool
    content: str
    error: str = ""
    cached: bool = False
    elapsed_s: float = 0.0
    model: str = ""
    attempts: int = 0


def _key(system: str, user: str, thinking: bool) -> str:
    h = hashlib.sha256()
    for part in (system, "\x00<SEP>\x00", user, str(thinking)):
        h.update(part.encode("utf-8", "replace"))
    return h.hexdigest()


def chat(
    user: str,
    system: str = "You are a precise assistant.",
    thinking: bool = False,
    use_cache: bool = True,
    max_retries: int = MAX_RETRIES,
    tag: str = "",
) -> LLMResponse:
    """Single chat completion via z-ai CLI, cached."""
    global _seq
    _seq += 1
    my_seq = _seq
    key = _key(system, user, thinking)
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
    for attempt in range(1, max_retries + 1):
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
                last_err = out.get("error", "bridge-unknown")[:300]
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
            time.sleep(2 * attempt)
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

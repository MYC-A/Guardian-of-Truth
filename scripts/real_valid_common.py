"""Shared infrastructure for running the frozen Guardian B4h-sound-v2 pipeline
on the public AI Journey valid.parquet cases (competition-real-valid-codex).

Gold firewall (directive): inference receives ONLY {id, prompt, response}.
Labels/explanations are joined post-seal in a separate scoring step.

Environment adapter (documented, not semantic): the frozen run used the BAI
provider (qwen3.8-flash). No BAI credential is available in this environment,
so the semantic backend runs on Z.ai GLM-4.7-Flash through the SAME ChatClient
transport, the SAME JsonExtractBackend (first-balanced-JSON extraction) and the
SAME E2ECachingBackend memoization, with response_format_mode='none' exactly as
the frozen BAI configuration did. All proposals are persisted to a
content-addressed cache so every run is replayable and auditable.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

VALID_PARQUET = REPO_ROOT / "valid.parquet"
OUT_DIR = REPO_ROOT / "outputs" / "vnext" / "real_valid_b"

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"
ZAI_MODEL = "GLM-4.7-Flash"
ZAI_MAX_OUTPUT_TOKENS = 8192   # thinking model: reasoning tokens share the budget
ZAI_TIMEOUT_SECONDS = 240.0
ZAI_MAX_RETRIES = 8
ZAI_INTERVAL_SECONDS = 1.0

# Mistral fallback/primary. At baseline time (2026-09-16 ~19:10 UTC) the Z.ai
# GLM-4.7-Flash endpoint was saturated (100% HTTP 429 over 8+8 probes, code
# 1305 "temporarily overloaded"), making the required ~1-2k proposals
# infeasible. The user-provided Mistral key serves the user's own example
# model ministral-14b-latest without rate limiting. Mistral small/medium are
# NOT available to this key (429). Provider choice is recorded in every run
# artifact; each provider gets its own content-addressed cache file (never
# mixed). Both providers run with response_format_mode='none' (the frozen BAI
# transport mode; guardian schemas use uniqueItems which strict JSON-schema
# endpoints reject).
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_MODEL = "ministral-14b-latest"
MISTRAL_MAX_OUTPUT_TOKENS = 8192
MISTRAL_TIMEOUT_SECONDS = 180.0
MISTRAL_MAX_RETRIES = 6
MISTRAL_INTERVAL_SECONDS = 0.35

PROVIDERS = {
    "mistral": dict(base_url=MISTRAL_BASE_URL, model=MISTRAL_MODEL,
                    api_key_env="MISTRAL_API_KEY",
                    max_output_tokens=MISTRAL_MAX_OUTPUT_TOKENS,
                    timeout_seconds=MISTRAL_TIMEOUT_SECONDS,
                    max_retries=MISTRAL_MAX_RETRIES,
                    interval_seconds=MISTRAL_INTERVAL_SECONDS,
                    drop_reasoning_effort=True),
    "zai": dict(base_url=ZAI_BASE_URL, model=ZAI_MODEL,
                api_key_env="Z_AI_API_KEY",
                max_output_tokens=ZAI_MAX_OUTPUT_TOKENS,
                timeout_seconds=ZAI_TIMEOUT_SECONDS,
                max_retries=ZAI_MAX_RETRIES,
                interval_seconds=ZAI_INTERVAL_SECONDS,
                drop_reasoning_effort=False),
}

# Outer transport retries: the ChatClient bounds HTTP-level retries at 8
# (rate-limit storms on a shared endpoint exhaust that in ~2 minutes).
# This wrapper retries the TRANSPORT only (same task, same payload, same
# schema) and never retries a schema-invalid or semantically wrong proposal.
OUTER_TRANSPORT_RETRIES = 4
OUTER_RETRY_DELAY_SECONDS = 20.0


class _OuterTransportRetry:
    """Transport-level outer retry around a JsonExtractBackend.

    Retries only ChatClientError with retryable=True (rate_limit/server/
    timeout/connection). A schema-invalid answer is NEVER re-proposed: the
    wrapper re-raises the Proposal exactly as the inner backend returned it.
    """

    def __init__(self, inner, *, attempts: int, delay: float, sleep=time.sleep):
        self._inner = inner
        self._attempts = attempts
        self._delay = delay
        self._sleep = sleep
        self.outer_retries = 0

    def propose(self, task: str, payload: dict, schema: dict):
        from guardian_truth.llm_client import ChatClientError

        last = None
        for attempt in range(self._attempts + 1):
            try:
                return self._inner.propose(task, payload, schema)
            except Exception as error:  # noqa: BLE001
                if not isinstance(error, ChatClientError) or not error.retryable:
                    raise
                last = error
                if attempt < self._attempts:
                    self.outer_retries += 1
                    self._sleep(self._delay)
        raise last


def load_firewalled_rows():
    """Return the inference-side view of valid.parquet: id/prompt/response only.

    The label/explanation columns are read in the separate scoring step
    (score_real_valid.py), never here."""
    import pandas as pd

    frame = pd.read_parquet(VALID_PARQUET)
    rows = []
    for _, row in frame.iterrows():
        rows.append({"id": str(row["id"]), "prompt": str(row["prompt"]),
                     "response": str(row["response"])})
    return rows


class _ProviderCompatClient:
    """Transport-level provider compatibility shim around ChatClient.

    Mistral's OpenAI-compatible endpoint rejects the `reasoning_effort`
    request parameter (HTTP 400 code 3051, non-retryable) while the frozen
    JsonExtractBackend passes reasoning_effort='low' on every call (the frozen
    BAI provider accepted it). The parameter is a transport-level hint with no
    semantic effect, so this shim drops it for providers that do not support
    it. Everything else (payload, retries, schema handling) is byte-identical
    to the frozen ChatClient behavior.
    """

    def __init__(self, client, *, drop_reasoning_effort: bool):
        self._client = client
        self._drop = drop_reasoning_effort

    def validate_configuration(self):
        return self._client.validate_configuration()

    def complete(self, messages, *, schema=None, budget=None, reasoning_effort=None):
        if self._drop:
            reasoning_effort = None
        return self._client.complete(messages, schema=schema, budget=budget,
                                     reasoning_effort=reasoning_effort)


def _load_env_key(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    return None


def build_backend(cache_path: Path, *, provider: str = "mistral",
                  interval_seconds: float | None = None):
    """Semantic backend on the selected provider with the frozen E2E
    caching/memoization. Provider choice is an ENVIRONMENT setting (the frozen
    run used BAI qwen3.8-flash; no BAI credential exists here)."""
    from guardian_truth.llm_client import ChatClient, ClientConfig
    from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend
    from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend

    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    settings = dict(PROVIDERS[provider])
    if interval_seconds is not None:
        settings["interval_seconds"] = interval_seconds
    api_key = _load_env_key(settings["api_key_env"])
    if not api_key:
        raise SystemExit(f"{settings['api_key_env']} not configured (env or .env)")
    os.environ[settings["api_key_env"]] = api_key

    config = ClientConfig(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key_env=settings["api_key_env"],
        timeout_seconds=settings["timeout_seconds"],
        max_output_tokens=settings["max_output_tokens"],
        max_retries=settings["max_retries"],
        response_format_mode="none",
    )
    client = _ProviderCompatClient(
        ChatClient(config), drop_reasoning_effort=bool(settings.get("drop_reasoning_effort")))
    client.validate_configuration()
    inner = JsonExtractBackend(client, interval_seconds=settings["interval_seconds"])
    transport = _OuterTransportRetry(
        inner, attempts=OUTER_TRANSPORT_RETRIES, delay=OUTER_RETRY_DELAY_SECONDS)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    return E2ECachingBackend(transport, cache_path=cache_path)


def b4h_sound_v2_guardian(backend, *, max_worlds: int = 4096):
    """The frozen B4h-sound-v2 configuration: historical H0 policy frontend +
    Conservative goal frontend, cycle-3 B3 semantics (SND-01..SND-11 included
    in the frozen source)."""
    from guardian_truth.vnext.adapters import AdapterMode
    from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
    from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS

    return GuardianE2EV1(
        backend,
        arm=E2EArmConfig("B4h-sound-v2", ("h0_hist",), ("conservative",)),
        max_worlds=max_worlds,
        adapter_mode=AdapterMode.AUDIT,
        enable_t2=True,
        semantics=SEMANTICS_ARMS["B3"],
    )


def save_progress(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


def load_progress(path: Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []

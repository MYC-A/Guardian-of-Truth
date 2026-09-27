"""Shared infrastructure for the operation-check research arms.

Span matching, suite loading, output helpers and a cached Mistral client
that reads MISTRAL_API_KEY / MISTRAL_MODEL from the server env file and
never prints the key. Runners never import gold files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
FROZEN_DIR = ROOT / "frozen"
OUTPUTS_DIR = Path(os.environ.get("OC_OUTPUTS", ROOT / "outputs"))
ENV_FILE = Path("/workspace/guardian/secrets/mistral.env")

ROLE_VOCAB = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
              "COMMUNICATION", "OTHER", "UNKNOWN"}
RELATION_VOCAB = {"GATE", "ORDER_BEFORE", "ORDER_AFTER", "EXCEPTION",
                  "EVEN_IF", "NONE", "UNKNOWN"}
PAIR_LABEL_VOCAB = {"REALIZES_OPERATION", "CHECKS_PRECONDITION", "OBSERVES_STATE",
                    "COMMUNICATES", "UNRELATED", "UNKNOWN"}

_SUITE_FILES = {
    "original": "frozen_cases.json",
    "renamed": "frozen_cases_renamed.json",
    "mini": "frozen_cases_mini.json",
    "mini_renamed": "frozen_cases_mini_renamed.json",
}
_COMP_FILES = {
    "original": "component_inputs.json",
    "renamed": "component_inputs_renamed.json",
    "mini": "component_inputs_mini.json",
    "mini_renamed": "component_inputs_mini.json",
}


def suffix_for(suite: str) -> str:
    if suite == "renamed":
        return "_renamed"
    if suite == "mini":
        return "_mini"
    if suite == "mini_renamed":
        return "_mini_renamed"
    return ""


# ---------------------------------------------------------------- env / api

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
        self.usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

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
        for attempt in range(14):
            if self.next_call > time.monotonic():
                time.sleep(self.next_call - time.monotonic())
            self.next_call = time.monotonic() + 3.0
            request = urllib.request.Request(
                "https://api.mistral.ai/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Authorization": "Bearer " + self.key,
                         "Content-Type": "application/json"})
            t0 = time.monotonic()
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
            finally:
                pass
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
        blob = cleaned[start:end]
        blob = re.sub(r",\s*([}\]])", r"\1", blob)
        try:
            value = json.loads(blob)
        except ValueError as exc:
            return {}, f"decode:{exc}"
        if not isinstance(value, dict):
            return {}, "not_object"
        return value, ""


# ---------------------------------------------------------------- suites

def load_suite(which: str = "original") -> list[dict]:
    path = FROZEN_DIR / _SUITE_FILES.get(which, "frozen_cases.json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_component_inputs(which: str = "original") -> dict[str, list[str]]:
    """Gold-derived SPANS ONLY (no roles, no tools) for component arms."""
    path = FROZEN_DIR / _COMP_FILES.get(which, "component_inputs.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {rec["case_id"]: rec["spans"] for rec in data}


def out_dir(arm: str) -> Path:
    d = OUTPUTS_DIR / arm
    d.mkdir(parents=True, exist_ok=True)
    return d


def arm_report_path(arm: str) -> Path:
    return out_dir(arm) / "_usage.json"


def write_usage(arm: str, payload: dict):
    path = arm_report_path(arm)
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    existing.update(payload)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- spans

def l1(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def all_occurrences(policy: str, span: str) -> list[tuple[int, int]]:
    """Exact case-sensitive occurrences of span in policy."""
    out = []
    start = 0
    while True:
        idx = policy.find(span, start)
        if idx < 0:
            return out
        out.append((idx, idx + len(span)))
        start = idx + 1


def l1_occurrences(policy: str, span: str) -> list[tuple[int, int]]:
    """Occurrences under L1 normalisation (casefold + whitespace collapse).

    Builds a char map from the normalised form back to original offsets.
    """
    # normalise with index mapping
    norm_chars = []
    index_map = []  # norm position -> original index of the char kept
    i = 0
    n = len(policy)
    while i < n:
        ch = policy[i]
        if ch.isspace():
            j = i
            while j < n and policy[j].isspace():
                j += 1
            norm_chars.append(" ")
            index_map.append(i)  # first whitespace char position
            i = j
        else:
            low = ch.casefold()
            for k, c in enumerate(low):
                norm_chars.append(c)
                index_map.append(i)
            i += 1
    norm = "".join(norm_chars)
    target = re.sub(r"\s+", " ", span.casefold()).strip()
    out = []
    start = 0
    while True:
        idx = norm.find(target, start)
        if idx < 0:
            return out
        orig_start = index_map[idx]
        orig_end = index_map[idx + len(target) - 1] + 1
        out.append((orig_start, orig_end))
        start = idx + 1
    # unreachable


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def validate_span(policy: str, span: str) -> bool:
    return isinstance(span, str) and bool(span) and span in policy

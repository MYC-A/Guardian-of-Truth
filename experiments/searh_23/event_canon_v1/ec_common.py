"""Shared infrastructure for the EVENT_CANON_v1 research arms."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PL_DIR = ROOT.parent / "policy_licensing_v1"
sys.path.insert(0, str(PL_DIR))

from pl_common import Mistral, render_tool, tools_by_name  # noqa: E402

FROZEN = Path(os.environ.get("EC_FROZEN", ROOT / "frozen"))
OUTPUTS = Path(os.environ.get("EC_OUTPUTS", ROOT / "outputs"))

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(policy: str):
    return [s.strip() for s in _SENT_SPLIT.split(policy) if s.strip()]


def sentence_of_span(policy: str, start: int):
    pos, k = 0, 0
    for s in _SENT_SPLIT.split(policy):
        if pos <= start < pos + len(s):
            return s.strip(), k
        pos += len(s) + 1
        k += 1
    return None, -1


def local_context(policy: str, start: int, window: int = 1):
    """Containing sentence plus up to `window` preceding sentences."""
    sents = sentences(policy)
    _, k = sentence_of_span(policy, start)
    if k < 0:
        return policy
    lo = max(0, k - window)
    return " ".join(sents[lo:k + 1])


def load_suite(which: str = "original", split: str | None = None):
    fname = {"original": "frozen_cases.json",
             "renamed": "frozen_cases_renamed.json"}[which]
    cases = json.loads((FROZEN / fname).read_text(encoding="utf-8"))
    if split:
        cases = [c for c in cases if c["split"] == split]
    return cases


def load_pairs_gold():
    return json.loads((FROZEN / "pairs_gold.json").read_text(encoding="utf-8"))


def out_dir(name: str) -> Path:
    d = OUTPUTS / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_usage(arm: str, payload: dict):
    import time as _time
    path = out_dir(arm) / "_usage.json"
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    existing.update(payload)
    existing.setdefault("written_at", _time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def event_by_cid(case):
    return {e["cid"]: e for e in case["canonical_events"]}


def mention_by_mid(case):
    return {m["mid"]: m for m in case["mentions"]}


MODELS = {
    "mistral": "ministral-14b-latest",
    "codestral": "codestral-latest",
}

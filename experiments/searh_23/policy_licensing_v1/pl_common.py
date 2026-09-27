"""Shared infrastructure for the policy-licensing research arms.

Loads the frozen suite (cases with events/edges/evidence/pair universe),
provides name-blind rendering, sentence handling and output dirs. The
Mistral client is reused from ../operation_check/oc_common.py (cached,
temperature 0, usage tracking).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OC_DIR = ROOT.parent / "operation_check"
sys.path.insert(0, str(OC_DIR))

from oc_common import Mistral  # noqa: E402

FROZEN = ROOT / "frozen"
OUTPUTS = Path(os.environ.get("PL_OUTPUTS", ROOT / "outputs"))

ROLE_VOCAB = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
              "COMMUNICATION", "OTHER", "UNKNOWN"}

RELATION_DEFS = {
    "PRECONDITION": "The antecedent event is an executable check that must be performed and pass before the target operation may be carried out.",
    "STATE_GATE": "The antecedent event is a state of affairs that must hold (be true) before the target operation may be carried out; no action is executed, the state is observed.",
    "ORDER_BEFORE": "The antecedent operation must be carried out before the target operation (sequencing between two business operations).",
    "ORDER_AFTER": "The antecedent operation must be carried out after the target operation (reverse direction).",
    "RESPONSE": "When the antecedent event happens or completes, the target action becomes obligatory (triggered obligation, e.g. a notification or archival duty).",
    "EXCEPTION": "The target operation is forbidden unless the antecedent holds ('unless' / negative gate).",
    "EVEN_IF": "The antecedent is explicitly stated NOT to block the target operation (documented non-blocking relation).",
    "NOT_SUPPORTED": "The two events are meaningfully connected, but the connection has no supported Guardian semantics.",
    "UNKNOWN": "The relation type cannot be determined from the policy text.",
}

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


def load_suite(which: str = "original", split: str | None = None):
    fname = {"original": "frozen_cases.json",
             "renamed": "frozen_cases_renamed.json"}[which]
    cases = json.loads((FROZEN / fname).read_text(encoding="utf-8"))
    if split:
        cases = [c for c in cases if c["split"] == split]
    return cases


def load_cf_links():
    return json.loads((FROZEN / "cf_links.json").read_text(encoding="utf-8"))


def load_splits():
    return json.loads((FROZEN / "splits.json").read_text(encoding="utf-8"))


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


def render_tool(tool) -> str:
    """Name-blind rendering: description + schema, never the tool name."""
    inp = ", ".join(f"{k}: {v}" for k, v in tool.get("input", {}).items()) or "none"
    outp = ", ".join(f"{k}: {v}" for k, v in tool.get("output", {}).items()) or "none"
    return f"{tool['description']} Input parameters: {inp}. Output: {outp}."


def tools_by_name(case) -> dict:
    return {t["name"]: t for t in case["tools"]}


def event_tool_desc(event, case) -> str:
    by_name = tools_by_name(case)
    parts = [render_tool(by_name[n]) for n in event.get("governed_tools", [])
             if n in by_name]
    return " ".join(parts)


def ev_by_eid(case):
    return {e["eid"]: e for e in case["events"]}


def gold_edge_pairs(case):
    """Set of frozenset({a_eid, b_eid}) connected by a gold edge (unordered)."""
    return {frozenset((e["from_eid"], e["to_eid"])) for e in case["edges"]}


def gold_direction(case):
    """Set of (from_eid, to_eid) ordered tuples from gold edges."""
    return {(e["from_eid"], e["to_eid"]) for e in case["edges"]}


MODELS = {
    "mistral": "ministral-14b-latest",
    "codestral": "codestral-latest",
}

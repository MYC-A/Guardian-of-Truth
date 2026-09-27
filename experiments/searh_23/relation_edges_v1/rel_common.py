"""Shared infrastructure for the relation-edges research arms.

Suite loading (frozen cases + relation inputs, joined by case_id), name-blind
tool rendering, sentence handling, pair universe construction, output dirs.
The Mistral client and usage writer are reused from the operation_check
research (../operation_check/oc_common.py).
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

from oc_common import Mistral, write_usage  # noqa: E402

FROZEN = ROOT / "frozen"
OUTPUTS = Path(os.environ.get("REL_OUTPUTS", ROOT / "outputs"))

ROLE_VOCAB = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
              "COMMUNICATION", "OTHER", "UNKNOWN"}
TO_SIDE_ROLES = ("OPERATION_EFFECT", "COMMUNICATION")

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

_SUITE_FILES = {
    "original": ("frozen_cases.json", "relation_inputs.json"),
    "renamed": ("frozen_cases_renamed.json", "relation_inputs_renamed.json"),
    "mini": ("frozen_cases_mini.json", "relation_inputs_mini.json"),
    "mini_renamed": ("frozen_cases_mini_renamed.json", "relation_inputs_mini_renamed.json"),
}


def suffix_for(suite: str) -> str:
    return {"renamed": "_renamed", "mini": "_mini",
            "mini_renamed": "_mini_renamed"}.get(suite, "")


def load_suite(which: str):
    cases_file, rel_file = _SUITE_FILES[which]
    cases = json.loads((FROZEN / cases_file).read_text(encoding="utf-8"))
    rel_inputs = {r["case_id"]: r for r in json.loads((FROZEN / rel_file).read_text(encoding="utf-8"))}
    for c in cases:
        c["events"] = rel_inputs[c["case_id"]]["events"]
    return cases


def out_dir(name: str) -> Path:
    d = OUTPUTS / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_tool(tool) -> str:
    """Name-blind rendering: description + schema, never the tool name."""
    inp = ", ".join(f"{k}: {v}" for k, v in tool.get("input", {}).items()) or "none"
    outp = ", ".join(f"{k}: {v}" for k, v in tool.get("output", {}).items()) or "none"
    return f"{tool['description']} Input parameters: {inp}. Output: {outp}."


def tools_by_name(case) -> dict:
    return {t["name"]: t for t in case["tools"]}


def event_tool_desc(event, case) -> str:
    """Rendered descriptions of the event's governed tools (name-blind)."""
    by_name = tools_by_name(case)
    parts = [render_tool(by_name[n]) for n in event.get("governed_tools", [])
             if n in by_name]
    return " ".join(parts)


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(policy: str):
    return [s.strip() for s in _SENT_SPLIT.split(policy) if s.strip()]


def sentence_of(span: str, policy: str):
    """Return (sentence containing the span, sentence index) or (None, -1)."""
    idx = policy.find(span)
    if idx < 0:
        return None, -1
    end = idx + len(span)
    pos = 0
    for i, s in enumerate(sentences(policy)):
        start = policy.find(s, pos)
        send = start + len(s)
        if start <= idx and end <= send:
            return s, i
        pos = send
    return None, -1


def pair_universe(events):
    """Ordered (from_event, to_event) candidate pairs over ALL non-descriptive
    events in both directions (a != b). The to-side includes checks and state
    observations because nested policies can gate a check itself (cond-on-cond
    chains, e.g. 'the inspection requires the chamber to be pre-chilled')."""
    side = [e for e in events if e["role"] != "OTHER"]
    return [(a, b) for a in side for b in side if a["source_span"] != b["source_span"]]


def norm_minmax(values):
    """Per-query min-max normalisation to [0, 1]."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]

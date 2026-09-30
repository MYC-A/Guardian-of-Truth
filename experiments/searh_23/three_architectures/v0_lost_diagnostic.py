#!/usr/bin/env python3
"""Diagnostic: deep-dive the 7 lost V0 hits (old structural TP, new V0 miss).

For each case:
  - target response tool calls + their schema check vs catalog
  - policy statements in the prompt relevant to the old rule classes
  - what the old channel fired (from flash baseline.json traces)
  - what V1/V3 judges said (from the new audit files)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as tc  # noqa: E402

REPO = HERE.parent.parent.parent  # experiments/searh_23/three_architectures -> repo
LOST = [
    "airline__21::t7",
    "airline__23::t10",
    "airline__44::t22",
    "airline__9::t6",
    "retail__27::t10",
    "telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27",
    "telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13",
]

OLD_FINDINGS = {
    "airline__21::t7": ["multiple_tool_calls_in_turn"],
    "airline__23::t10": ["missing_argument x16", "multiple_tool_calls_in_turn"],
    "airline__44::t22": ["multiple_tool_calls_in_turn"],
    "airline__9::t6": ["multiple_tool_calls_in_turn"],
    "retail__27::t10": ["multiple_tool_calls_in_turn"],
    "telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27": ["mixed_text_and_tool_call"],
    "telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13": ["date_gated_action_violation"],
}

POLICY_PATTERNS = [
    (r"one tool call|single tool call|only one call|at most one|per turn|per message|one action at a time|sequential", "call-frequency"),
    (r"date|before .{0,40}(allowed|permitted)|no earlier than|not before", "date-gate"),
    (r"both (text|prose).{0,40}(tool|call)|either.{0,30}(text|call)", "text+call"),
]


def gold_labels():
    g = {}
    for line in open(HERE / "data" / "public46_gold.csv"):
        parts = line.strip().split(",")
        if parts[0] != "id":
            g[parts[0]] = int(parts[1])
    return g


def judge_labels():
    """Per-case labels from V1 audit (gemma greedy) and V3 audit (per-slot votes)."""
    out = {}
    for stage, path in (("V1", HERE / "outputs/public46_v_full/p46_V1_audit.jsonl"),
                        ("V3", HERE / "outputs/public46_v_full/p46_V3_audit.jsonl")):
        for line in open(path):
            d = json.loads(line)
            votes = {}
            for v in d.get("votes", []):
                key = f"{v.get('family')}#{v.get('slot')}"
                votes[key] = v["vote"]["label"] if v.get("valid") else None
            out.setdefault(d["id"], {})[stage] = votes
    return out


def schema_report(ctx):
    """Re-run _check_schema for target-response calls."""
    issues = []
    for call in ctx.target().tool_calls:
        tool = ctx.catalog.tools.get(call.name) if ctx.catalog else None
        if tool is None:
            issues.append(f"NON-CATALOG {call.name}")
            continue
        for hit in tc._check_schema(call, tool):
            issues.append(f"{call.name}: {hit.kind} {hit.detail}")
    return issues


def policy_snippets(prompt):
    """Pull policy-ish statements from the SYSTEM block."""
    m = re.search(r"⟦SYSTEM⟧(.*?)(?:⟦USER⟧|⟦ASSISTANT⟧|$)", prompt, re.DOTALL)
    sys_text = m.group(1) if m else prompt[:6000]
    hits = []
    for pat, tag in POLICY_PATTERNS:
        for mm in re.finditer(pat, sys_text, re.IGNORECASE):
            s = max(0, mm.start() - 120)
            e = min(len(sys_text), mm.end() + 160)
            hits.append((tag, sys_text[s:e].replace("\n", " ")))
    return sys_text, hits


def main():
    gold = gold_labels()
    judges = judge_labels()
    cases = {}
    for row in tc.load_cases_csv(HERE / "data" / "public46.csv"):
        if row["id"] in LOST:
            cases[row["id"]] = tc.parse_case(row["id"], row["prompt"], row["response"])

    for cid in LOST:
        ctx = cases[cid]
        print("=" * 100)
        print(f"CASE {cid}  gold={gold.get(cid)}  old_findings={OLD_FINDINGS[cid]}")
        tv = judges.get(cid, {})
        print(f"  V1 gemma greedy: {tv.get('V1', {}).get('gemma#1')}")
        print(f"  V3 votes: {tv.get('V3')}")
        print(f"  target turn: {len(ctx.target().tool_calls)} tool call(s), "
              f"turn_count={len(ctx.turns)}")
        for call in ctx.target().tool_calls:
            print(f"    - {call.name}({call.args_raw[:200]!r})")
        print(f"  schema report (target only): {schema_report(ctx) or 'CLEAN'}")
        print(f"  suspicions: {[s.kind + ': ' + s.detail[:80] for s in ctx.suspicions] or 'none'}")
        print(f"  structural hits: {[h.reason for h in ctx.structural_hits] or 'none'}")
        # target response text
        resp_text = ctx.target().text.strip()
        print(f"  target text ({len(resp_text)} chars): {resp_text[:400]!r}")
        # policy snippets
        sys_text, hits = policy_snippets(ctx.prompt_raw)
        if hits:
            print(f"  POLICY MATCHES in SYSTEM block ({len(sys_text)} chars):")
            for tag, snip in hits[:6]:
                print(f"    [{tag}] ...{snip}...")
        else:
            print(f"  POLICY MATCHES: none in SYSTEM block ({len(sys_text)} chars)")
        # history call count for missing_argument check
        n_hist_calls = sum(len(t.tool_calls) for t in ctx.history_turns())
        print(f"  history: {n_hist_calls} tool calls total")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Patch evasiveness v2 artifacts: honesty caveat on mechanical justification + bare-class gold stats."""
import json
from pathlib import Path

OUT = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23/outputs/searh_23/evasiveness_targeted")

a = json.loads((OUT / "analysis_v2.json").read_text(encoding="utf-8"))
rh = a["refusal_handoff_justification"]
gold1 = sum(1 for r in rh if r["gold"] == 1)
a["refusal_handoff_justification_caveat"] = (
    "JUSTIFIED_BY_POLICY_SPAN here means ONLY that a candidate English policy clause "
    "matching generic grounding words (must/required/confirmation/escalation/...) exists "
    "in the case policy — span existence != entailment. It discriminates nothing: "
    f"{len(rh)}/{len(rh)} refusal/handoff cases have candidate spans while {gold1}/{len(rh)} "
    "are actually gold=1. Verifying refusal justification needs claim-level mapping "
    "(the investigator/s8-card binding problem), not a keyword span.")
a["bare_class_gold_note"] = (
    "bare-TOOL_CALL is 15/17 gold=1 (P .88 R .65 vs gold) — a strong structural property "
    "of public46 (most injected errors manifest as premature/bare tool calls). Using "
    "'is_bare_tool_call' directly as a predictor would be benchmark-specific "
    "overfitting: report as characterization, NOT as a proposed detector.")
(OUT / "analysis_v2.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")

rep = (OUT / "report_v2.md").read_text(encoding="utf-8")
rep += f"""
## Honesty caveats
- 'JUSTIFIED_BY_POLICY_SPAN' = candidate clause exists (keyword span). It does NOT verify
  the specific refusal maps to the specific clause: {len(rh)}/{len(rh)} have candidates,
  {gold1}/{len(rh)} are gold=1 — the mechanical grounding discriminates nothing.
- bare-TOOL_CALL class is {a['bare_tool_call_class']} (15/17 gold=1): characterization of
  public46 error injection, NOT a proposed detector (would be overfitting).
- function_call mode: applicable in principle (tool defs inside <policy>), extraction not built.
"""
(OUT / "report_v2.md").write_text(rep, encoding="utf-8")
print("patched; rh:", len(rh), "gold1:", gold1)

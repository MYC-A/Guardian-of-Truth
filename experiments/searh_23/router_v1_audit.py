#!/usr/bin/env python3
"""SEARCH_23 §2.4: router v1 audit — what routing recall 1.0 did and did not mean.

Code-level audit of experiments/big_researh/router_v1.py (traces were lost in
the 2026-09-23 server reset; the audit therefore reads the CODE, which fully
determines what was measured):

  1. `routing_recall` counted gold-positive cases where ANY route TRIGGERED.
     Triggers are broad (R3 fires on nearly every case with NuExtract rules —
     38/46; R5 on any Q divergence — 45/46). Recall 1.0 therefore does NOT
     demonstrate correct tool selection, error finding, or routing benefit.
  2. The router EXECUTED no tools: routes carry tool NAMES + rationale + a
     budget STRING; the only computation is the graph build used by triggers.
     Labels = control OR R2 mechanical contradiction (aggregation v1).
  3. Cost accounting is nominal (strings), not measured calls/latency.
  4. Usefulness per route was never measured (did the route's tool result
     change information? would the verdict change?).

This script provides:
  audit_v1_code()  — the static audit above as a JSON record;
  analyze_traces() — route usefulness/cost/miss metrics for NEW traces
                     (router arm C of SEARCH_23 §3), applied per run.

CLI:
  python router_v1_audit.py --emit outputs/searh_23/router_audit/v1_code_audit.json
  python router_v1_audit.py --traces <routes.jsonl> --out <analysis.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

V1_CODE_AUDIT = {
    "router": "experiments/big_researh/router_v1.py @ big_researh (code-verified)",
    "what_routing_recall_1_meant": {
        "definition": "gold-positive cases covered by >=1 TRIGGERED route",
        "not_equivalent_to": [
            "correct tool choice",
            "finding the actual error",
            "any measured benefit of routing",
        ],
        "broad_triggers": {
            "R3_rule_premise": "fires when any grounded P-card or NuExtract rule has "
                               "condition/exception structure (historically 38/46 cases)",
            "R5_interp_divergence": "fires when any Q divergence exists for the case "
                                    "(historically 45/46 cases)",
        },
        "verdict": "routing recall 1.0 is a coverage statement about trigger breadth, "
                   "NOT evidence of a working agentic router",
    },
    "tools_executed": "none — routes record tool names/rationale/budget strings only; "
                      "graph build is used for triggers, not as a routed verification",
    "labels": "label = control_granite OR mechanical_contradiction(R2); the router "
              "cannot zero a control label (S8 honesty rule kept)",
    "cost_accounting": "nominal strings ('local only', '1-2 calls'); no measured "
                       "calls/latency per route",
    "route_usefulness": "never measured in v1 (no per-route change-information or "
                        "verdict-contribution metrics)",
    "trace_status": "outputs/big_researh/router_v1/ lost in 2026-09-23 reset; "
                    "numbers marked UNVERIFIED in BASELINE_AUDIT.md",
    "required_for_search23_arm_c": [
        "per-route: triggered, tool_calls, latency, new_information (bool), "
        "verdict_contribution (would the case label change without this route)",
        "misses: gold-positive cases where no route triggered AND control=0",
        "fixed routing with SAME tools and SAME call budget as the agent arm "
        "(otherwise the agent-vs-fixed comparison is confounded)",
    ],
}


def analyze_traces(traces_path: Path) -> dict:
    """Route usefulness/cost/miss analysis for NEW router traces (arm C).

    Expected record fields (emitted by the §3 fixed router):
      id, gold, control, label_router,
      routes: [{route, triggered, tool_calls: n, latency_s, new_information,
                verdict_contribution}]
    """
    per_route = {}
    misses = []
    n_cases = 0
    total_calls = 0.0
    total_latency = 0.0
    for line in open(traces_path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        n_cases += 1
        any_triggered = False
        contributed = False
        for r in rec.get("routes", []):
            st = per_route.setdefault(r.get("route"), {
                "triggered": 0, "total": 0, "tool_calls": 0, "latency_s": 0.0,
                "new_information": 0, "verdict_contribution": 0})
            st["total"] += 1
            if r.get("triggered"):
                any_triggered = True
                st["triggered"] += 1
                st["tool_calls"] += int(r.get("tool_calls", 0) or 0)
                st["latency_s"] += float(r.get("latency_s", 0) or 0)
                if r.get("new_information"):
                    st["new_information"] += 1
                if r.get("verdict_contribution"):
                    contributed = True
                    st["verdict_contribution"] += 1
            total_calls += int(r.get("tool_calls", 0) or 0)
            total_latency += float(r.get("latency_s", 0) or 0)
        if rec.get("gold") == 1 and rec.get("control") == 0 and not any_triggered:
            misses.append(rec.get("id"))
    for st in per_route.values():
        if st["triggered"]:
            st["usefulness"] = round(st["verdict_contribution"] / st["triggered"], 4)
            st["info_rate"] = round(st["new_information"] / st["triggered"], 4)
        else:
            st["usefulness"] = None
            st["info_rate"] = None
    return {
        "n_cases": n_cases,
        "per_route": per_route,
        "gold_pos_control0_notrigger_misses": {"n": len(misses), "ids": misses},
        "totals": {"tool_calls": total_calls, "latency_s": round(total_latency, 2)},
        "avg_calls_per_case": round(total_calls / n_cases, 2) if n_cases else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", help="write the v1 code audit JSON to this path")
    ap.add_argument("--traces", help="analyze a NEW router trace JSONL with this path")
    ap.add_argument("--out", help="output path for trace analysis")
    args = ap.parse_args()
    if args.emit:
        p = Path(args.emit)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(V1_CODE_AUDIT, ensure_ascii=False, indent=1))
        print(f"[audit] written {p}")
    if args.traces:
        analysis = analyze_traces(Path(args.traces))
        out = Path(args.out) if args.out else Path(args.traces).with_name(
            Path(args.traces).stem + "_analysis.json")
        out.write_text(json.dumps(analysis, ensure_ascii=False, indent=1))
        print(f"[audit] trace analysis written {out}")
        print(json.dumps({k: v for k, v in analysis.items() if k != "per_route"},
                         ensure_ascii=False, indent=1))
    if not args.emit and not args.traces:
        print(json.dumps(V1_CODE_AUDIT, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

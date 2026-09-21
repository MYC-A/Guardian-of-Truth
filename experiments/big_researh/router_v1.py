#!/usr/bin/env python3
"""BIG_RESEARH Stage II.A: deterministic verification router (no routing LLM).

Directive II.A: minimal router — input: obligation/suspicion type + available
sources; output: applicable tools, selection rationale, budget, expected result
type. The main detector (structural Guardian + old Granite control) ALWAYS
stays the control channel: the router may only ADD mechanically verified
violations, never silently drop error classes it did not recognize.

Routes (deterministic triggers over already-computed channel outputs):
  R1 tool_claim:      response has tool-call arguments -> python/graph check
                      (tool call <-> result, status, entity). Trigger: any
                      response call event. Escalation: ambiguous text result ->
                      LangExtract facts (S6) -> Mistral NL question (Stage III).
  R2 entity_mixing:   graph scope_conflict / value_conflict / observed_mismatch
                      -> graph/provenance code. Mechanical contradiction.
  R3 rule_premise:    P cards / S9 rules with condition+exception -> premise
                      selection; all premises verified -> Clingo (S8); else
                      UNKNOWN (never coerced).
  R4 refusal:         P card obligation_kind == refusal -> supported granite
                      mode + policy context (measured separately; v1: context
                      only, no new granite mode run — documented).
  R5 interp_divergence: Q divergences (verified) -> discriminating question.

Aggregation v1 (fixed BEFORE the run, honest):
  label_router = control_granite OR mechanical_contradiction(R2)
  mechanical_contradiction := any response argument with status in
  {observed_mismatch, value_conflict, scope_conflict}
  The router NEVER zeroes a control label in v1 (one safe card does not prove
  the whole response error-free — S8 documented).

Metrics: F1 vs control/baseline; routing recall (gold=1 cases with >=1 route
triggered); cases dropped by router (no route at all); per-route trigger
stats; FN/FP attribution per route.

Outputs: outputs/big_researh/router_v1/{routes.jsonl, summary.json}
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "src"))

from guardian_truth.parsing import parse_events  # noqa: E402
from guardian_truth.provenance import build_graph  # noqa: E402
from run_granite_modes import read_cases  # noqa: E402

INPUT_CSV = REPO / "outputs" / "full21" / "input" / "public46_label_free.csv"
CONTROL_PERCASE = REPO / "outputs" / "full21" / "control_repro_percase.csv"
P_CARDS = REPO / "outputs" / "big_researh" / "p_api" / "extract" / "cards.jsonl"
S9_CARDS = REPO / "outputs" / "big_researh" / "s9_nuextract" / "cards.jsonl"
S6_API_RECORDS = REPO / "outputs" / "full21" / "s6_langextract_api" / "records.jsonl"
S8_CARDS = REPO / "outputs" / "big_researh" / "s8_clingo" / "cards_verified.jsonl"
Q_DIVS = REPO / "outputs" / "big_researh" / "q_discrim" / "divergences.jsonl"
OUT_DIR = REPO / "outputs" / "big_researh" / "router_v1"


def load_jsonl(path: Path) -> list:
    out = []
    if path.is_file():
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def metrics(pred: dict, gold: dict):
    tp = fp = fn = tn = miss = 0
    for cid, g in gold.items():
        if cid not in pred:
            miss += 1
            continue
        p = pred[cid]
        tp += p == 1 and g == 1
        fp += p == 1 and g == 0
        fn += p == 0 and g == 1
        tn += p == 0 and g == 0
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "no_pred": miss,
            "P": round(pr, 4), "R": round(rc, 4), "F1": round(f1, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(INPUT_CSV))
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = read_cases(Path(args.input))
    gold, control, baseline = {}, {}, {}
    for row in csv.DictReader(open(CONTROL_PERCASE)):
        gold[row["id"]] = int(row["gold"])
        control[row["id"]] = int(row["granite_repro"])
        baseline[row["id"]] = int(row["baseline"])

    p_cards = {r["id"]: r for r in load_jsonl(P_CARDS) if r.get("status") == "OK"}
    s9 = {r["id"]: r for r in load_jsonl(S9_CARDS)}
    s6 = {r["id"]: r for r in load_jsonl(S6_API_RECORDS)}
    s8 = {}
    for r in load_jsonl(S8_CARDS):
        s8.setdefault(r["id"], []).append(r)
    q_divs = {}
    for r in load_jsonl(Q_DIVS):
        q_divs.setdefault(r["id"], []).append(r)

    route_stats = {}
    pred_router, pred_control = {}, {}
    routing_recall_hits = 0
    gold_pos = 0
    dropped_by_router = []
    records = []
    for case in cases:
        cid = case["id"]
        routes = []

        # ---- R1 tool_claim: response has tool-call arguments ----
        try:
            history = parse_events(case["prompt"], "prompt")
            candidate = parse_events(case["response"], "response")
            graph = build_graph(history, candidate)
        except Exception as e:
            history, candidate, graph = None, None, None
            routes.append({"route": "R1_tool_claim", "triggered": False,
                           "error": f"graph build failed: {type(e).__name__}"})
        if graph is not None:
            has_calls = any(e.kind == "call" for e in (candidate or []))
            bad_args = [a for a in graph.arguments
                        if a.status in ("not_observed", "observed_mismatch",
                                        "scope_conflict", "value_conflict")]
            if has_calls:
                tools = ["python:tool_call_result_check", "graph:provenance"]
                rationale = (f"response contains {sum(1 for e in candidate if e.kind == 'call')} "
                             "tool call(s); check call<->result, status, entity binding")
                if bad_args:
                    tools += ["langextract:facts", "mistral:nl_question"]
                    rationale += "; ambiguous/unverified argument values present -> escalation"
                routes.append({"route": "R1_tool_claim", "triggered": True,
                               "tools": tools, "rationale": rationale,
                               "budget": "python/graph: local; NL: 1-2 calls",
                               "expected_result": "per-argument observed/mismatch status",
                               "n_args_flagged": len(bad_args)})
            else:
                routes.append({"route": "R1_tool_claim", "triggered": False,
                               "note": "no tool call in response"})

        # ---- R2 entity_mixing: mechanical contradiction in graph ----
        if graph is not None:
            contradictions = [a for a in graph.arguments
                              if a.status in ("observed_mismatch", "value_conflict",
                                              "scope_conflict")]
            if contradictions:
                routes.append({"route": "R2_entity_mixing", "triggered": True,
                               "tools": ["graph:provenance", "python:entity_scope_check"],
                               "rationale": "response argument value conflicts with "
                                            "observed facts / entity scope",
                               "budget": "local only",
                               "expected_result": "mechanical contradiction evidence",
                               "evidence": [{"arg_path": "/".join(map(str, a.path)),
                                             "status": a.status} for a in contradictions[:6]]})
            else:
                routes.append({"route": "R2_entity_mixing", "triggered": False,
                               "note": "no scope/value conflicts"})

        # ---- R3 rule_premise: P cards / S9 rules with cond/exception ----
        pc = p_cards.get(cid, {})
        grounded_cards = [c for c in pc.get("cards", []) if c.get("quote_grounded")]
        s9_rules = s9.get(cid, {}).get("policy_rules") or []
        formalizable = [c for c in grounded_cards
                        if c.get("applicability_condition") or c.get("exceptions")]
        s8_recs = s8.get(cid, [])
        if formalizable or any(r.get("condition_text") or r.get("exception_text")
                               for r in s9_rules if isinstance(r, dict)):
            clingo_verdicts = [r.get("verdict") for r in s8_recs]
            routes.append({"route": "R3_rule_premise", "triggered": True,
                           "tools": ["ruleir:premise_selection", "clingo:check",
                                     "checker:revalidation"],
                           "rationale": f"{len(formalizable)} grounded P-card(s) / "
                                        f"{len(s9_rules)} NuExtract rule(s) with "
                                        "condition/exception structure",
                           "budget": "local only (clingo)",
                           "expected_result": "violated/safe/unknown per card",
                           "clingo_verdicts": {"violated": clingo_verdicts.count("violated"),
                                               "safe": clingo_verdicts.count("safe"),
                                               "unknown": clingo_verdicts.count("unknown")}})
        else:
            routes.append({"route": "R3_rule_premise", "triggered": False,
                           "note": "no formalizable card/rule"})

        # ---- R4 refusal ----
        refusal_cards = [c for c in grounded_cards
                         if str(c.get("obligation_kind")) == "refusal"]
        if refusal_cards:
            routes.append({"route": "R4_refusal", "triggered": True,
                           "tools": ["granite:supported_mode", "policy:context"],
                           "rationale": "refusal obligation present; verify duty/exception, "
                                        "not auto-label 1",
                           "budget": "1 granite mode call (v1: context-only, documented)",
                           "expected_result": "duty/exception assessment"})
        else:
            routes.append({"route": "R4_refusal", "triggered": False})

        # ---- R5 interp_divergence ----
        divs = q_divs.get(cid, [])
        verified_divs = [d for d in divs if d.get("q_verified")]
        if divs:
            routes.append({"route": "R5_interp_divergence", "triggered": True,
                           "tools": ["q:discriminating_question"],
                           "rationale": f"{len(divs)} interpretation divergence(s), "
                                        f"{len(verified_divs)} mechanically verified",
                           "budget": "1 NL call per divergence + local span check",
                           "expected_result": "deciding policy words + repaired element"})
        else:
            routes.append({"route": "R5_interp_divergence", "triggered": False})

        # ---- aggregation v1 (fixed): control OR mechanical contradiction ----
        mech_contra = any(r["route"] == "R2_entity_mixing" and r.get("triggered")
                          for r in routes)
        ctl = control.get(cid)
        label = None if ctl is None else (1 if (ctl == 1 or mech_contra) else 0)
        pred_router[cid] = label
        pred_control[cid] = ctl

        any_route = any(r.get("triggered") for r in routes)
        if gold.get(cid) == 1:
            gold_pos += 1
            if any_route:
                routing_recall_hits += 1
        if not any_route:
            dropped_by_router.append(cid)

        for r in routes:
            st = route_stats.setdefault(r["route"], {"triggered": 0, "total": 0})
            st["total"] += 1
            st["triggered"] += int(bool(r.get("triggered")))

        records.append({"id": cid, "gold": gold.get(cid), "control": ctl,
                        "baseline": baseline.get(cid), "routes": routes,
                        "mechanical_contradiction": mech_contra,
                        "label_router_v1": label})

    with open(OUT_DIR / "routes.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # metrics on the covered subset (control available)
    scored_pred = {k: v for k, v in pred_router.items() if v is not None}
    summary = {
        "aggregation_v1": "label = control_granite OR mechanical_contradiction(R2); "
                          "router never zeroes a control label (S8 honesty rule)",
        "control_only": metrics(pred_control, gold),
        "router_v1": metrics(scored_pred, gold),
        "router_added_1_over_control": sum(
            1 for c in scored_pred if scored_pred[c] == 1 and pred_control.get(c) == 0),
        "routing_recall": {
            "gold_positive": gold_pos,
            "covered_by_any_route": routing_recall_hits,
            "recall": round(routing_recall_hits / gold_pos, 4) if gold_pos else None},
        "cases_dropped_by_router": {"n": len(dropped_by_router), "ids": dropped_by_router},
        "route_trigger_stats": route_stats,
        "note_R4": "v1 records the route and rationale; no separate granite refusal-mode "
                   "run yet — documented as not executed, not as negative",
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

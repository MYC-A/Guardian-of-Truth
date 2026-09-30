#!/usr/bin/env python3
"""System-level integration: full-auto verdicts, multi-Phi consensus,
oracle decomposition factorial (directive §26-34, §73, §84-88).

Full-auto path per case:
  RAW trajectory -> auto Step1 programs (Phi1/Phi2) -> documented/auto
  Step2 contracts -> auto Step3 claims -> auto Step4 goal (refusals)
  -> frozen proof runtime -> verdict.

Consensus semantics:
  universal          verdict accepted only if ALL Phi agree
  error_existential  ERROR if any Phi proves ERROR (research arm; a wrong
                     Phi can cause false ERROR - measured, not assumed)

Oracle decomposition: gold at exactly one step, automatic at the rest.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parent / "system_integration_v1"))

from v2_llm import chat  # noqa: E402
from step1_arms import (  # noqa: E402
    load_split, families_of, run_s1a, gold_programs_for,
    PRIMARY, SECONDARY)
from steps_2to4 import (  # noqa: E402
    acquire_auto_contracts, enriched_case, step3_raw, step4_goal,
    validate_goal)
from v2_suite_builder import as_case, oracle_claim
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import (
    ReviewedProgram, check_call, check_claim, decide_reviewed)
from guardian_truth.integration.reachability import (
    ReviewedGoal, assess_local_reachability, decide_refusal)


def auto_programs(fam, case, model):
    programs, _, _ = run_s1a(fam, model)
    out = []
    catalog_names = {t.get("name") for t in case.tools}
    for p in programs:
        if p["governed_tool"] not in catalog_names:
            continue
        d = {k: p[k] for k in ("policy", "governed_tool",
                               "governed_description", "entity_argument",
                               "gate", "when")}
        d["governed_producer"] = producer_scope(case, p["governed_tool"])
        d["evidence_source"] = "AUTO_VERIFIED"
        d["complete_for_governed_action"] = bool(
            p.get("complete_for_governed_action"))
        try:
            out.append(ReviewedProgram(**d))
        except Exception:
            continue
    return out


def gold_programs_runtime(fam, case):
    out = []
    catalog_names = {t.get("name") for t in case.tools}
    for p in gold_programs_for(fam, ""):
        if p["governed_tool"] not in catalog_names:
            continue
        d = {k: p[k] for k in ("policy", "governed_tool",
                               "governed_description", "entity_argument",
                               "gate", "when")}
        d["governed_producer"] = producer_scope(case, p["governed_tool"])
        d["evidence_source"] = "HUMAN_REVIEWED"
        d["complete_for_governed_action"] = True
        out.append(ReviewedProgram(**d))
    return out


def verdict_for(row, case, programs, facts, claims_mode, split_gold,
                goal=None, refusal=None, response_index=None):
    """One runtime pass; claims_mode: none|auto|gold."""
    resp_idx = row["target_response"]["index"]
    actions = tuple(check_call(p, case, c, tuple(facts))
                    for p in programs for c in case.calls
                    if c.tool == p.governed_tool and c.index < resp_idx)
    claims = ()
    inventory_complete = True
    if claims_mode == "gold":
        queries = []
        for label in split_gold[row["case_id"]]["claims"]:
            try:
                queries.append(oracle_claim(row, label, case))
            except Exception:
                pass
        claims = tuple(check_claim(q, case, tuple(facts)) for q in queries)
        inventory_complete = bool(queries) or not split_gold[row["case_id"]]["claims"]
    elif claims_mode == "auto":
        raw = step3_raw(row)
        if raw is not None:
            from guardian_truth.integration.automatic_claims import (
                compile_candidate_claims)
            compiled = compile_candidate_claims(
                row["target_response"]["text"], resp_idx, case, raw)
            claims = tuple(check_claim(q, case, tuple(facts))
                           for q in compiled.queries)
            inventory_complete = compiled.inventory_complete
        else:
            inventory_complete = False
    reviewed = decide_reviewed(actions, claims,
                               policy_complete=bool(programs) and all(
                                   p.complete_for_governed_action
                                   for p in programs),
                               claim_inventory_complete=inventory_complete)
    # refusal branch: ordinary replies are NOT_APPLICABLE (the runtime's
    # reviewed_non_refusal semantics); refusal cases compute or stay UNKNOWN
    refusal_status = "NOT_APPLICABLE"
    if "reviewed_goal" in row:
        if goal is not None and refusal is not None:
            reach = assess_local_reachability(
                row["user_request"], row["target_response"]["text"], resp_idx,
                goal, programs, case, tuple(facts), catalog_complete=True)
            refusal_dec = decide_refusal(row["target_response"]["text"],
                                         refusal, reach)
            refusal_status = refusal_dec["status"]
        else:
            refusal_status = "UNKNOWN"
    if "ERROR" in {reviewed["status"], refusal_status}:
        return "ERROR"
    if (reviewed["status"] == "NO_ERROR"
            and refusal_status in {"NO_ERROR", "NOT_APPLICABLE"}):
        return "NO_ERROR"
    return "UNKNOWN"


def run_config(split, programs_mode, contracts_mode, claims_mode, goal_mode):
    """One cell of the factorial. modes: auto|gold|none per step."""
    inputs, split_gold = load_split(split)
    fams = {f["family"]: f for f in families_of(inputs)}
    rows = []
    for row in inputs:
        fam = fams[row["family"]]
        needs_auto = any(not t.get("documented_contracts")
                         for t in row["available_tools"])
        row2 = row
        if needs_auto and contracts_mode == "auto":
            auto = acquire_auto_contracts(row["available_tools"], "swift")
            row2 = enriched_case(row, auto, contrastive_model="swift")
        elif needs_auto and contracts_mode == "gold":
            from v2_suite_builder import LAB_ORACLE_CONTRACTS
            row2 = enriched_case(row, {n: {"contracts": c} for n, c in
                                       LAB_ORACLE_CONTRACTS.items()})
        case = as_case(row2)
        facts, _, _ = facts_from_documented(case)
        # programs
        if programs_mode == "gold":
            programs = gold_programs_runtime(fam, case)
            phi_sets = [programs]
        else:
            p1 = auto_programs(fam, case, PRIMARY)
            p2 = auto_programs(fam, case, SECONDARY)
            phi_sets = [p1, p2]
        # claims
        cmode = claims_mode
        # goal
        goal = refusal = None
        if "reviewed_goal" in row:
            if goal_mode == "gold":
                goal = ReviewedGoal(**row["reviewed_goal"])
                refusal = row["reviewed_refusal"]
            elif goal_mode == "auto":
                parsed = step4_goal(row)
                validated, issues = validate_goal(parsed, row)
                if validated:
                    try:
                        goal = ReviewedGoal(**validated["goal"])
                        refusal = validated["refusal"]
                    except Exception:
                        goal = refusal = None
        verdicts = []
        for programs in phi_sets:
            v = verdict_for(row, case, programs, facts, cmode, split_gold,
                            goal=goal, refusal=refusal)
            verdicts.append(v)
        # consensus semantics
        universal = verdicts[0] if len(set(verdicts)) == 1 else "UNKNOWN"
        err_exist = "ERROR" if "ERROR" in verdicts else (
            "NO_ERROR" if set(verdicts) == {"NO_ERROR"} else "UNKNOWN")
        expected = split_gold[row["case_id"]]["verdict"]
        rows.append({
            "case_id": row["case_id"], "phi_verdicts": verdicts,
            "universal": universal, "error_existential": err_exist,
            "gold": expected,
        })
    return rows


def score(rows, key):
    c = Counter()
    for r in rows:
        got = r[key]
        c.update({"total": 1, "correct": int(got == r["gold"]),
                  "pred_" + str(got): 1, "gold_" + r["gold"]: 1,
                  "false_alarm": int(got == "ERROR" and r["gold"] != "ERROR"),
                  "error_hidden": int(got == "UNKNOWN" and r["gold"] == "ERROR")})
    decided = c["pred_ERROR"] + c["pred_NO_ERROR"]
    return {"total": c["total"], "correct": c["correct"],
            "exact_3way": round(c["correct"] / max(1, c["total"]), 3),
            "decided": decided,
            "decided_coverage": round(decided / max(1, c["total"]), 3),
            "accuracy_decided": round(
                (c["pred_ERROR"] + c["pred_NO_ERROR"] - c["false_alarm"]
                 - sum(1 for r in rows if r[key] == "NO_ERROR"
                       and r["gold"] != "NO_ERROR")) / max(1, decided), 3),
            "error_recall": round(
                sum(1 for r in rows if r[key] == "ERROR"
                    and r["gold"] == "ERROR") / max(1, c["gold_ERROR"]), 3),
            "false_ERROR": c["false_alarm"],
            "unknown_rate": round(c["pred_UNKNOWN"] / max(1, c["total"]), 3),
            "error_hidden_unknown": c["error_hidden"]}


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "sealed"
    configs = {
        # oracle decomposition factorial (§85): gold at exactly one step
        "full_auto_universal": ("auto", "auto", "auto", "auto"),
        "full_auto_err_exist": ("auto", "auto", "auto", "auto"),
        "gold_S1": ("gold", "auto", "auto", "auto"),
        "gold_S2": ("auto", "gold", "auto", "auto"),
        "gold_S3": ("auto", "auto", "gold", "auto"),
        "gold_S4": ("auto", "auto", "auto", "gold"),
        "oracle_ceiling": ("gold", "gold", "gold", "gold"),
    }
    out = {}
    for name, (pm, cm, clm, gm) in configs.items():
        rows = run_config(split, pm, cm, clm, gm)
        key = "universal" if "universal" in name else "error_existential"
        if name.startswith("gold_") or name == "oracle_ceiling":
            key = "universal"  # single phi (gold) - same value
        s = score(rows, key)
        out[name] = {"config": {"programs": pm, "contracts": cm,
                                "claims": clm, "goal": gm},
                     "score": s, "rows": rows}
        print(split, name, json.dumps(s))
        sys.stdout.flush()
    # material ambiguity stats on full-auto
    fa = out["full_auto_universal"]["rows"]
    div = [r for r in fa if len(set(r["phi_verdicts"])) > 1]
    out["material_ambiguity"] = {
        "divergent_cases": len(div),
        "divergent_ids": [r["case_id"] for r in div],
        "phi_disagreement_rate": round(len(div) / max(1, len(fa)), 3),
    }
    print(split, "material_ambiguity", json.dumps(out["material_ambiguity"]))
    path = HERE / "outputs" / f"system_{split}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1,
                               default=str), encoding="utf-8")
    print("saved", path)


if __name__ == "__main__":
    main()

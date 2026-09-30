#!/usr/bin/env python3
"""Build + SELF-VERIFY + freeze trajectories_v2.

Self-verification (before freezing): for every case, run the FROZEN proof
runtime with gold programs + gold facts + gold claims and require the
resulting verdict to equal the authored gold verdict. Prose-only families
are verified under injected oracle contracts (their ceiling). A case that
does not reproduce is a suite bug, not a runtime change: fix the case.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parent / "system_integration_v1"))

from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.integration.claim_binding import (
    containing_sentence_span, literal_scope_arguments)
from guardian_truth.integration.proof_engine import (
    ClaimQuery, ReviewedProgram, check_call, check_claim, decide_reviewed)
from guardian_truth.step2.result_types import scalar_to_json

import v2_domains_dev as DEV

RO = "READ_OBSERVATION"
CG = "CONTRACT_GUARANTEE"

# oracle contracts for prose-only tools (what correct acquisition recovers)
LAB_ORACLE_CONTRACTS = {
    "run_sterility_check": [{
        "entity_argument": "sample_id", "result_entity_path": "$.sample_id",
        "result_value_path": "$.sterile", "predicate": "sample.sterile",
        "strength": "OBSERVED", "allowed_values": [],
        "meaning": "Reports whether the sample passed the sterility check."}],
    "run_purity_check": [{
        "entity_argument": "sample_id", "result_entity_path": "$.sample_id",
        "result_value_path": "$.pure", "predicate": "sample.pure",
        "strength": "OBSERVED", "allowed_values": [],
        "meaning": "Reports whether the sample passed the purity check."}],
    "check_priority": [{
        "entity_argument": "sample_id", "result_entity_path": "$.sample_id",
        "result_value_path": "$.priority", "predicate": "sample.priority",
        "strength": "OBSERVED", "allowed_values": [],
        "meaning": "Reports whether the sample holds priority status."}],
    "release_sample": [{
        "entity_argument": "sample_id", "result_entity_path": "$.sample_id",
        "result_value_path": "$.state", "predicate": "sample.release_state",
        "strength": "EXECUTED", "allowed_values": ["released"],
        "meaning": "Releases the sample; state=released means completion."}],
}


def as_case(row: dict, oracle_contracts: dict | None = None) -> TrajectoryCase:
    tools = [dict(t) for t in row["available_tools"]]
    if oracle_contracts:
        for t in tools:
            if t["name"] in oracle_contracts:
                t["documented_contracts"] = oracle_contracts[t["name"]]
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"], e["arguments"])
                  for e in row["history"]
                  if e["role"] == "assistant" and "tool" in e)
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"], e["payload"])
                    for e in row["history"] if e["role"] == "tool")
    return TrajectoryCase(row["case_id"], row["system_policy"], "suite_author",
                          tuple(tools), calls, results)


def gold_programs(family: dict, case: TrajectoryCase) -> list[ReviewedProgram]:
    out = []
    catalog_names = {t.get("name") for t in case.tools}
    for p in family["programs"]():
        if p["governed_tool"] not in catalog_names:
            continue  # catalog subset case: program not applicable
        d = dict(p)
        d["governed_producer"] = producer_scope(case, p["governed_tool"])
        out.append(ReviewedProgram(**d))
    return out


def oracle_claim(row: dict, label: dict, case: TrajectoryCase) -> ClaimQuery:
    bindings = [b for b in acquire_documented(case).bindings
                if b.predicate == label["predicate"]]
    entity_types = {b.entity_type for b in bindings}
    entity_type = next(iter(entity_types)) if len(entity_types) == 1 else ""
    response = row["target_response"]["text"]
    span = containing_sentence_span(response, label["start"], label["end"])
    scope_text = response[span[0]:span[1]] if span else label["quote"]
    scope = literal_scope_arguments(case, label["predicate"], label["entity"],
                                    scope_text)
    return ClaimQuery(response, row["target_response"]["index"],
                      label["quote"], label["start"], label["end"],
                      label["mode"], label["predicate"], entity_type,
                      label["entity"], label["value"], "HUMAN_REVIEWED_ORACLE",
                      "ASSISTANT" if label["quote"].startswith("I ") else "UNSPECIFIED",
                      scope or (), span)


def verify_case(family: dict, case_def: dict, oracle_contracts=None) -> dict:
    """Run frozen runtime with gold inputs; return match report."""
    tools = family["tools"]
    subset = case_def.get("catalog_subset")
    if subset:
        tools = [t for t in tools if t["name"] in subset]
    row = {
        "case_id": case_def["case_id"],
        "system_policy": family["policy"],
        "available_tools": tools,
        "history": case_def["history"],
        "target_response": case_def["target_response"],
    }
    case = as_case(row, oracle_contracts)
    programs = gold_programs(family, case)

    if case_def.get("refusal"):
        # Step 4 branch: goal + refusal + no claims
        from guardian_truth.integration.reachability import (
            ReviewedGoal, assess_local_reachability, decide_refusal)
        goal = ReviewedGoal(**family["goal_builder"](case_def))
        refusal = {"evidence_source": "HUMAN_REVIEWED",
                   "quote": case_def["target_response"]["text"],
                   "absolute_inability": True}
        from guardian_truth.integration.contracts import facts_from_documented
        facts, _, _ = facts_from_documented(case)
        reach = assess_local_reachability(
            case_def["user_request"], case_def["target_response"]["text"],
            case_def["target_response"]["index"], goal, programs, case,
            tuple(facts), catalog_complete=True)
        refusal_decision = decide_refusal(case_def["target_response"]["text"],
                                          refusal, reach)
        status = refusal_decision["status"]
        if status == "ERROR":
            verdict_status = "ERROR"
        elif status == "NO_ERROR":
            verdict_status = "UNKNOWN"  # claim inventory absent (v1 semantics)
        else:
            verdict_status = "UNKNOWN"
        return {
            "case_id": case_def["case_id"],
            "verdict_expected": case_def["verdict"],
            "verdict_got": verdict_status,
            "reachability_expected": case_def.get("reachability"),
            "reachability_got": reach["status"],
            "match": verdict_status == case_def["verdict"]
            and (case_def.get("reachability") in (None, reach["status"])),
            "fact_match": True,
            "gold_facts": 0, "got_facts": 0,
            "missing_facts": 0, "extra_facts": 0,
            "acquisition_issues": [],
        }

    from guardian_truth.integration.contracts import facts_from_documented
    facts, assessments, issues = facts_from_documented(case)
    verified = tuple(facts)
    actions = tuple(check_call(p, case, c, verified)
                    for p in programs for c in case.calls
                    if c.tool == p.governed_tool)
    labels = [f(row["target_response"]["text"]) if callable(f) else f
              for f in case_def["claims"]]
    claims = tuple(check_claim(oracle_claim(row, label, case), case, verified)
                   for label in labels)
    verdict = decide_reviewed(actions, claims,
                              policy_complete=all(
                                  p.complete_for_governed_action for p in programs)
                              and bool(programs),
                              claim_inventory_complete=True)
    # fact-level verification against gold world_facts
    gold_facts = {json.dumps({k: f[k] for k in
                              ("predicate", "entity", "value", "strength",
                               "authority", "json_path", "source_call_id",
                               "source_result_index")},
                             sort_keys=True, default=str)
                  for f in case_def["world_facts"]}
    got_facts = set()
    for v in verified:
        f = v.fact.as_dict()
        got_facts.add(json.dumps({
            "predicate": f["predicate"], "entity": json.loads(f["entity_id"]),
            "value": json.loads(f["value"]), "strength": f["strength"],
            "authority": f["authority"],
            "json_path": f["provenance"]["json_path"],
            "source_call_id": f["provenance"]["call_id"],
            "source_result_index": f["provenance"]["result_index"]},
            sort_keys=True, default=str))
    return {
        "case_id": case_def["case_id"],
        "verdict_expected": case_def["verdict"],
        "verdict_got": verdict["status"],
        "verdict_reason": verdict["reason"],
        "match": verdict["status"] == case_def["verdict"],
        "fact_match": gold_facts == got_facts,
        "gold_facts": len(gold_facts), "got_facts": len(got_facts),
        "missing_facts": len(gold_facts - got_facts),
        "extra_facts": len(got_facts - gold_facts),
        "acquisition_issues": list(issues),
    }


def build_split_rows(families: list[dict], oracle_contracts_by_family: dict,
                     split: str):
    inputs, gold = [], []
    for family in families:
        oc = oracle_contracts_by_family.get(family["name"])
        for case_def in family["cases"]:
            labels = [f(case_def["target_response"]["text"]) if callable(f) else f
                      for f in case_def["claims"]]
            tools = family["tools"]
            subset = case_def.get("catalog_subset")
            if subset:
                tools = [t for t in tools if t["name"] in subset]
            entry = {
                "case_id": case_def["case_id"],
                "family": family["name"],
                "mechanisms": case_def["mechanisms"],
                "system_policy": family["policy"],
                "user_request": case_def["user_request"],
                "available_tools": tools,
                "history": case_def["history"],
                "target_response": case_def["target_response"],
                "completeness": {
                    "catalog_complete": True,
                    "history_complete": True,
                },
            }
            gold_entry = {
                "case_id": case_def["case_id"],
                "policy_constraints": [],
                "world_facts": case_def["world_facts"],
                "unsupported_facts": [],
                "claims": labels,
                "action_check": None,
                "reachability": case_def.get("reachability"),
                "verdict": case_def["verdict"],
                "proof_expectation": case_def["proof_expectation"],
                "oracle_contracts_required": bool(oc),
            }
            if case_def.get("refusal"):
                entry["reviewed_goal"] = family["goal_builder"](case_def)
                entry["reviewed_refusal"] = {
                    "evidence_source": "HUMAN_REVIEWED",
                    "quote": case_def["target_response"]["text"],
                    "absolute_inability": True,
                }
            inputs.append(entry)
            gold.append(gold_entry)
    return inputs, gold


def main():
    import v2_domains_sealed as SEALED
    oracle_contracts_by_family = {"lab": LAB_ORACLE_CONTRACTS}
    report = []
    for split, families in (("dev", DEV.DEV_FAMILIES),
                            ("sealed", SEALED.SEALED_FAMILIES)):
        for family in families:
            oc = oracle_contracts_by_family.get(family["name"])
            for case_def in family["cases"]:
                r = verify_case(family, case_def, oc)
                r["split"] = split
                report.append(r)
                flag = "OK " if (r["match"] and r["fact_match"]) else "FAIL"
                extra = ""
                if case_def.get("refusal"):
                    extra = f" reach {r.get('reachability_got')}"
                print(flag, split, r["case_id"], "verdict",
                      r["verdict_expected"], "=>", r["verdict_got"], extra)
    bad = [r for r in report if not (r["match"] and r["fact_match"])]
    print(f"\nself-verification: {len(report) - len(bad)}/{len(report)} cases reproduce")
    if bad:
        print("FAILURES:")
        for r in bad:
            print(" ", json.dumps(r, default=str)[:500])
        return 1
    # freeze both splits
    frozen = HERE / "frozen" / "trajectories_v2"
    frozen.mkdir(parents=True, exist_ok=True)
    manifest = {"suite": "system_trajectories_v2",
                "frozen_at": "2026-09-30",
                "counts": {},
                "files": {},
                "design": "self-verified against frozen proof runtime before freezing; "
                          "lab family verified under injected oracle contracts; "
                          "transit refusal cases follow v1 refusal semantics",
                }
    for split, families in (("dev", DEV.DEV_FAMILIES),
                            ("sealed", SEALED.SEALED_FAMILIES)):
        inputs, gold = build_split_rows(families, oracle_contracts_by_family, split)
        (frozen / f"{split}_inputs.json").write_text(
            json.dumps(inputs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (frozen / f"{split}_gold.json").write_text(
            json.dumps(gold, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        manifest["counts"][split] = len(inputs)
        manifest["files"][f"{split}_inputs.json"] = hashlib.sha256(
            (frozen / f"{split}_inputs.json").read_bytes()).hexdigest()
        manifest["files"][f"{split}_gold.json"] = hashlib.sha256(
            (frozen / f"{split}_gold.json").read_bytes()).hexdigest()
    (frozen / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("frozen:", manifest["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Paired dev ablation: reviewed policy, automatic Step 2 and Step 3 claims.

Uses cached model outputs from the frozen candidate-mode run. No policy or
claim gold enters inference; the reviewed policy program is marked oracle.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.automatic_claims import compile_candidate_claims
from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import (
    check_call, check_claim, decide_reviewed, load_reviewed_programs)
from eval_step2_documented import as_case

FROZEN = HERE / "frozen" / "trajectories_v1"


def run() -> dict:
    inputs = json.loads((FROZEN / "dev_inputs.json").read_text(encoding="utf-8"))
    candidate_run = json.loads((HERE / "outputs/step3_candidate_dev.json").read_text(encoding="utf-8"))
    raw_by_case = {r["case_id"]: r["prediction"]["raw"]
                   for r in candidate_run["per_case"]}
    programs = load_reviewed_programs(HERE / "reviewed_policy_programs_dev.json")
    predicted = []
    for row in inputs:
        case = as_case(row)
        candidates = [p for p in programs if p.policy == row["system_policy"]]
        if len(candidates) != 1:
            raise ValueError("reviewed program missing/ambiguous")
        program = candidates[0]
        facts, assessments, acquisition_issues = facts_from_documented(case)
        compiled = compile_candidate_claims(
            row["target_response"]["text"], row["target_response"]["index"],
            case, raw_by_case[row["case_id"]])
        actions = tuple(check_call(program, case, call, tuple(facts))
                        for call in case.calls if call.tool == program.governed_tool)
        claims = tuple(check_claim(query, case, tuple(facts)) for query in compiled.queries)
        verdict = decide_reviewed(actions, claims,
                                  policy_complete=program.complete_for_governed_action,
                                  claim_inventory_complete=compiled.inventory_complete)
        predicted.append({"case_id": row["case_id"], "predicted": verdict["status"],
                          "reason": verdict["reason"], "actions": actions,
                          "claims": claims, "compiled_queries": [q.__dict__ for q in compiled.queries],
                          "nonfactual": compiled.nonfactual, "issues": compiled.issues,
                          "inventory_complete": compiled.inventory_complete,
                          "fact_count": len(facts),
                          "assessment_issues": [a.issues for a in assessments if a.issues],
                          "acquisition_issues": acquisition_issues})
    gold = {r["case_id"]: r for r in json.loads(
        (FROZEN / "dev_gold.json").read_text(encoding="utf-8"))}
    counts = Counter()
    for row in predicted:
        expected = gold[row["case_id"]]["verdict"]
        row["expected"] = expected
        counts.update({"total": 1, "correct": int(expected == row["predicted"]),
                       "pred_" + row["predicted"]: 1,
                       "gold_" + expected: 1,
                       "gold_errors_hidden_unknown": int(expected == "ERROR"
                                                         and row["predicted"] == "UNKNOWN"),
                       "false_alarms": int(expected != "ERROR"
                                           and row["predicted"] == "ERROR")})
    report = {"track": "reviewed_policy_oracle__automatic_documented_step2__candidate_step3",
              "split": "dev", "counts": dict(counts), "per_case": predicted}
    out = HERE / "outputs" / "auto_claim_bridge_dev.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    run()

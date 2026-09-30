"""Oracle acquisition ablation: reviewed policy + claims, automatic Step 2.

Gold policy/claim interpretations are explicitly injected. The resulting
verdict is a proof-runtime upper bound, not an automatic Guardian score.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import acquire_documented, facts_from_documented
from guardian_truth.integration.claim_binding import (
    containing_sentence_span, literal_scope_arguments)
from guardian_truth.integration.proof_engine import (
    ClaimQuery, check_call, check_claim, decide_reviewed, load_reviewed_programs)
from eval_step2_documented import as_case

FROZEN = HERE / "frozen" / "trajectories_v1"


def oracle_claim(row: dict, label: dict, case) -> ClaimQuery:
    bindings = [b for b in acquire_documented(case).bindings
                if b.predicate == label["predicate"]]
    entity_types = {b.entity_type for b in bindings}
    entity_type = next(iter(entity_types)) if len(entity_types) == 1 else ""
    response = row["target_response"]["text"]
    span = containing_sentence_span(response, label["start"], label["end"])
    scope_text = response[span[0]:span[1]] if span else label["quote"]
    scope = literal_scope_arguments(case, label["predicate"], label["entity"],
                                    scope_text)
    return ClaimQuery(row["target_response"]["text"],
                      row["target_response"]["index"],
                      label["quote"], label["start"], label["end"],
                      label["mode"], label["predicate"], entity_type,
                      label["entity"], label["value"], "HUMAN_REVIEWED_ORACLE",
                      "ASSISTANT" if label["quote"].startswith("I ") else "UNSPECIFIED",
                      scope or (), span)


def run() -> dict:
    inputs = json.loads((FROZEN / "dev_inputs.json").read_text(encoding="utf-8"))
    labels = {r["case_id"]: r for r in json.loads(
        (FROZEN / "dev_gold.json").read_text(encoding="utf-8"))}
    programs = load_reviewed_programs(HERE / "reviewed_policy_programs_dev.json")
    per_case = []
    counts = Counter()
    for row in inputs:
        case = as_case(row)
        matching = [p for p in programs if p.policy == row["system_policy"]]
        if len(matching) != 1:
            raise ValueError(f"reviewed policy program missing/ambiguous: {row['case_id']}")
        program = matching[0]
        facts, assessments, acquisition_issues = facts_from_documented(case)
        verified = tuple(facts)
        actions = tuple(check_call(program, case, call, verified) for call in case.calls
                        if call.tool == program.governed_tool)
        claims = tuple(check_claim(oracle_claim(row, label, case), case, verified)
                       for label in labels[row["case_id"]]["claims"])
        verdict = decide_reviewed(actions, claims,
                                  policy_complete=program.complete_for_governed_action,
                                  claim_inventory_complete=True)
        expected = labels[row["case_id"]]["verdict"]
        counts.update({"correct": int(verdict["status"] == expected),
                       "total": 1, "pred_" + verdict["status"]: 1,
                       "gold_" + expected: 1})
        if labels[row["case_id"]]["action_check"] is not None:
            target = labels[row["case_id"]]["action_check"]
            selected = [a for a in actions if a.get("target_call_id") == target["call_id"]]
            counts.update({"action_correct": int(len(selected) == 1 and
                                                  selected[0]["status"] == target["status"]),
                           "action_total": 1})
        per_case.append({"case_id": row["case_id"], "expected": expected,
                         "predicted": verdict["status"],
                         "reason": verdict["reason"], "actions": actions,
                         "claims": claims, "fact_count": len(facts),
                         "assessment_issues": [a.issues for a in assessments if a.issues],
                         "acquisition_issues": acquisition_issues})
    report = {"track": "reviewed_policy_and_claim_oracle__automatic_documented_step2",
              "split": "dev", "counts": dict(counts), "per_case": per_case}
    out = HERE / "outputs" / "reviewed_bridge_dev.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    run()

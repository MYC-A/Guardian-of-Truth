"""Frozen local-reachability score; reviewed goals/policies are oracle inputs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import ReviewedProgram
from guardian_truth.integration.reachability import (
    ReviewedGoal, assess_local_reachability, decide_refusal)
from eval_step2_documented import as_case

FROZEN = HERE / "frozen" / "refusal_v1"


def run(split: str) -> dict:
    inputs = json.loads((FROZEN / f"{split}_inputs.json").read_text(encoding="utf-8"))
    predictions = []
    for row in inputs:
        case = as_case(row)
        facts, assessments, acquisition_issues = facts_from_documented(case)
        definition = row["reviewed_goal"]
        goal = ReviewedGoal(definition["quote"], definition["entity_type"],
                            definition["entity_id"], definition["predicate"],
                            definition["value"],
                            definition["candidate_actions_exhaustive"],
                            tuple(definition["candidate_calls"]),
                            definition["evidence_source"])
        programs = tuple(ReviewedProgram(**p) for p in row["reviewed_policy_programs"])
        response = row["target_response"]["text"]
        reach = assess_local_reachability(
            row["user_request"], response, row["target_response"]["index"],
            goal, programs, case, tuple(facts),
            catalog_complete=row["completeness"]["catalog_complete"])
        verdict = decide_refusal(response, row["reviewed_refusal"], reach)
        predictions.append({"case_id": row["case_id"],
                            "reachability": reach, "verdict": verdict,
                            "fact_count": len(facts),
                            "acquisition_issues": acquisition_issues,
                            "assessment_issues": [a.issues for a in assessments if a.issues]})
    gold = {row["case_id"]: row for row in json.loads(
        (FROZEN / f"{split}_gold.json").read_text(encoding="utf-8"))}
    counts = Counter()
    for row in predictions:
        expected = gold[row["case_id"]]
        row["expected_reachability"] = expected["reachability"]
        row["expected_verdict"] = expected["verdict"]
        got_reach = row["reachability"]["status"]
        got_verdict = row["verdict"]["status"]
        counts.update({"total": 1,
                       "reachability_correct": int(got_reach == expected["reachability"]),
                       "verdict_correct": int(got_verdict == expected["verdict"]),
                       "pred_reach_" + got_reach: 1,
                       "gold_reach_" + expected["reachability"]: 1,
                       "pred_verdict_" + got_verdict: 1,
                       "gold_verdict_" + expected["verdict"]: 1,
                       "false_alarms": int(got_verdict == "ERROR"
                                           and expected["verdict"] != "ERROR"),
                       "errors_hidden_unknown": int(got_verdict == "UNKNOWN"
                                                    and expected["verdict"] == "ERROR")})
    report = {"split": split,
              "track": "reviewed_policy_goal_refusal_oracle__automatic_documented_step2",
              "counts": dict(counts), "per_case": predictions}
    out = HERE / "outputs" / f"refusal_v1_{split}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "sealed"), default="dev")
    args = parser.parse_args()
    run(args.split)

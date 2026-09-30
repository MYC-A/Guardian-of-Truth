"""One entry-point diagnostic across frozen full trajectories and refusals.

Dev full-trajectory policy/non-refusal scopes and refusal goal/program scopes
are oracle-reviewed inputs. The model candidate claims are cached earlier raw
answers. This is not an automatic contest score.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.proof_engine import (
    ReviewedProgram, load_reviewed_programs)
from guardian_truth.integration.reachability import ReviewedGoal
from guardian_truth.integration.system_runtime import analyze_system_case
from eval_step2_documented import as_case


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _goal(row: dict) -> ReviewedGoal:
    d = row["reviewed_goal"]
    return ReviewedGoal(d["quote"], d["entity_type"], d["entity_id"],
                        d["predicate"], d["value"],
                        d["candidate_actions_exhaustive"],
                        tuple(d["candidate_calls"]), d["evidence_source"])


def run() -> dict:
    traj = HERE / "frozen" / "trajectories_v1"
    refusal = HERE / "frozen" / "refusal_v1"
    reviewed = load_reviewed_programs(HERE / "reviewed_policy_programs_dev.json")
    raw = {r["case_id"]: r["prediction"]["raw"] for r in
           _read(HERE / "outputs" / "step3_candidate_dev.json")["per_case"]}
    rows = []
    for row in _read(traj / "dev_inputs.json"):
        programs = tuple(p for p in reviewed if p.policy == row["system_policy"])
        result = analyze_system_case(
            as_case(row), response=row["target_response"]["text"],
            response_index=row["target_response"]["index"], programs=programs,
            reviewed_policy_scope_complete=len(programs) == 1,
            candidate_claim_raw=raw[row["case_id"]],
            reviewed_non_refusal=True)
        rows.append({"suite": "full_dev", "case_id": row["case_id"],
                     "prediction": result})
    for split in ("dev", "sealed"):
        for row in _read(refusal / f"{split}_inputs.json"):
            programs = tuple(ReviewedProgram(**p)
                             for p in row["reviewed_policy_programs"])
            result = analyze_system_case(
                as_case(row), response=row["target_response"]["text"],
                response_index=row["target_response"]["index"],
                programs=programs, reviewed_policy_scope_complete=False,
                reviewed_goal=_goal(row),
                reviewed_refusal=row["reviewed_refusal"],
                user_request=row["user_request"],
                catalog_complete=row["completeness"]["catalog_complete"])
            rows.append({"suite": f"refusal_{split}",
                         "case_id": row["case_id"], "prediction": result})

    gold = {}
    for row in _read(traj / "dev_gold.json"):
        gold[("full_dev", row["case_id"])] = row["verdict"]
    for split in ("dev", "sealed"):
        for row in _read(refusal / f"{split}_gold.json"):
            gold[(f"refusal_{split}", row["case_id"])] = row["verdict"]
    counts = {}
    for row in rows:
        suite = row["suite"]
        expected = gold[(suite, row["case_id"])]
        got = row["prediction"]["status"]
        row["gold_verdict"] = expected
        c = counts.setdefault(suite, Counter())
        c.update({"total": 1, "correct": int(got == expected),
                  "pred_" + got: 1, "gold_" + expected: 1,
                  "false_alarm": int(got == "ERROR" and expected != "ERROR"),
                  "error_hidden_unknown": int(got == "UNKNOWN"
                                              and expected == "ERROR")})
    report = {"track": "integrated_entry_point_with_declared_oracle_scopes",
              "counts": {k: dict(v) for k, v in counts.items()},
              "per_case": rows}
    path = HERE / "outputs" / "system_runtime_diagnostic.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return report


if __name__ == "__main__":
    run()

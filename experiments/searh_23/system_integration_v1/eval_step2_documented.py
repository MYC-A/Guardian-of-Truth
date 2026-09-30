"""Strict Step 2 score on the frozen system trajectories.

Inference receives only inputs. The scorer opens gold after all predictions
are constructed; this module is never imported by the detector.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase

FROZEN = HERE / "frozen" / "trajectories_v1"


def as_case(row: dict) -> TrajectoryCase:
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"], e["arguments"])
                  for e in row["history"]
                  if e["role"] == "assistant" and "tool" in e)
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"], e["payload"])
                    for e in row["history"] if e["role"] == "tool")
    return TrajectoryCase(row["case_id"], row["system_policy"], "suite_author",
                          tuple(row["available_tools"]), calls, results)


def predicted_key(row: dict) -> tuple:
    fact = row["fact"]
    return (fact["predicate"], json.loads(fact["entity_id"]),
            json.loads(fact["value"]), fact["strength"], fact["authority"],
            fact["provenance"]["call_id"],
            fact["provenance"]["result_index"],
            fact["provenance"]["json_path"])


def gold_key(row: dict) -> tuple:
    return (row["predicate"], row["entity"], row["value"], row["strength"],
            row["authority"], row["source_call_id"],
            row["source_result_index"], row["json_path"])


def run(split: str) -> dict:
    inputs = json.loads((FROZEN / f"{split}_inputs.json").read_text(encoding="utf-8"))
    predictions = {}
    for row in inputs:
        verified, assessments, acquisition_issues = facts_from_documented(as_case(row))
        predictions[row["case_id"]] = {
            "facts": [v.as_dict() for v in verified],
            "assessment_issues": [list(a.issues) for a in assessments if a.issues],
            "acquisition_issues": list(acquisition_issues),
        }
    gold = {r["case_id"]: r for r in json.loads(
        (FROZEN / f"{split}_gold.json").read_text(encoding="utf-8"))}
    total = Counter()
    cases = []
    for cid, pred in predictions.items():
        pk = set(predicted_key(x) for x in pred["facts"])
        gk = set(gold_key(x) for x in gold[cid]["world_facts"])
        tp, fp, fn = pk & gk, pk - gk, gk - pk
        total.update({"correct": len(tp), "extra": len(fp),
                      "missing": len(fn), "gold": len(gk), "predicted": len(pk)})
        cases.append({"case_id": cid, "family": cid.split(".")[0],
                      "correct": len(tp), "extra": len(fp), "missing": len(fn),
                      "extra_keys": [repr(x) for x in sorted(fp, key=repr)],
                      "missing_keys": [repr(x) for x in sorted(fn, key=repr)],
                      "assessment_issues": pred["assessment_issues"],
                      "acquisition_issues": pred["acquisition_issues"]})
    p = total["correct"] / max(1, total["predicted"])
    r = total["correct"] / max(1, total["gold"])
    report = {"split": split, "scope": "structured documented contracts only",
              "counts": dict(total), "precision": round(p, 4),
              "recall": round(r, 4), "per_case": cases}
    out = HERE / "outputs" / f"step2_documented_{split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "sealed"), default="dev")
    args = parser.parse_args()
    run(args.split)

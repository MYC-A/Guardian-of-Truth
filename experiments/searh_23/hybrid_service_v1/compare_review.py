"""Compare completed review arms to the exact complete source judge run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare_matrix import _load_records
from score_campaign import DATA, _family_bootstrap_delta

BASELINES = {
    "r0-refute-positive": "g0-direct", "r1-review-all": "g0-direct",
    "r2-ge-refute-positive": "g3-ge-gp-surface",
    "r3-ge-review-all": "g3-ge-gp-surface",
    "h3-native-review": "g0-direct",
    "h3-ge-native-review": "g3-ge-gp-surface",
}


def compare(source: Path, candidate: Path):
    before_config, before = _load_records(source)
    after_config, after = _load_records(candidate)
    if any(before_config[key] != after_config[key] for key in
           ("split", "input_sha256", "case_ids")):
        raise ValueError("source and candidate have different frozen inputs")
    ids = before_config["case_ids"]
    gold = {r["id"]: r for r in map(json.loads,
        (DATA / (before_config["split"] + "_gold.jsonl")).read_text(
            encoding="utf-8").splitlines())}
    report = {"schema": "review-paired/1", "source_run": str(source),
              "candidate_run": str(candidate), "n": len(ids), "arms": {}}
    for arm, records in after.items():
        if arm not in BASELINES:
            continue
        baseline_name = BASELINES[arm]
        baseline = before[baseline_name]
        recovered, harmed, same_wrong, changed = [], [], [], []
        for cid in ids:
            first = int(baseline[cid]["decision"] == "ERROR")
            second = int(records[cid]["decision"] == "ERROR")
            label = gold[cid]["label"]
            if first != second:
                changed.append({"id": cid, "gold": label,
                    "before": baseline[cid]["decision"],
                    "after": records[cid]["decision"],
                    "review": records[cid]["result"]["coverage"].get("counterevidence")})
            if first != label and second == label:
                recovered.append(cid)
            elif first == label and second != label:
                harmed.append(cid)
            elif first != label and second != label:
                same_wrong.append(cid)
        report["arms"][arm] = {"baseline": baseline_name,
            "recovered": recovered, "harmed": harmed, "same_wrong": same_wrong,
            "changes": changed,
            **_family_bootstrap_delta(gold, baseline, records, ids)}
    (candidate / "paired_review_score.json").write_text(json.dumps(
        report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("candidate", type=Path)
    args = p.parse_args()
    result = compare(args.source, args.candidate)
    print(json.dumps({arm: {"baseline": value["baseline"],
        "recovered": len(value["recovered"]), "harmed": len(value["harmed"]),
        "delta_f1_ci95_family_cluster": value["delta_f1_ci95_family_cluster"]}
        for arm, value in result["arms"].items()}, indent=2))

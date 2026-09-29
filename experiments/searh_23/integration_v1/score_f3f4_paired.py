"""Score complete F3/F4 paired replay from one frontend and two W1 arms."""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "step1_working_v1"))
from w1_score import score_case

HASHES = {
    "f3": "9937692879423293ae94791e5b0ae47b64a5bbdb791cf66eebf13d40637edb5c",
    "f4": "57a08403f07abd5c7bf0569fe995e2675a3b34e8444e86dc14e6ef3eea42a8d1",
}


def score(archive: Path) -> dict:
    report = {}
    with tarfile.open(archive, "r:gz") as saved:
        for suite in ("f3", "f4"):
            path = HERE.parent / "event_ie_frontends_v1/frozen" / f"level_{suite}_cases.json"
            if hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[suite]:
                raise ValueError("input hash changed")
            gold = json.loads(path.read_text(encoding="utf-8"))
            report[suite] = {}
            for arm in ("paired_baseline", "paired_guard"):
                totals = {k: 0 for k in ("correct_unique", "extra_strict",
                                          "missing_directed", "typed_unique",
                                          "exact_graph", "exact_typed_graph")}
                per_case = {}
                for case in gold:
                    member = f"experiments/searh_23/integration_v1/outputs/{arm}/W1_DOWN10_LLM_SG/{case['case_id']}.json"
                    row = score_case(case, json.load(saved.extractfile(member)))
                    per_case[case["case_id"]] = row
                    for key in totals:
                        totals[key] += row["counts"].get(key, 0)
                tp, fp, fn = (totals[k] for k in ("correct_unique", "extra_strict", "missing_directed"))
                report[suite][arm] = {
                    "correct": tp, "extra": fp, "missing": fn,
                    "precision": tp / (tp + fp) if tp + fp else 0,
                    "recall": tp / (tp + fn) if tp + fn else 0,
                    "typed": totals["typed_unique"],
                    "exact_graphs": totals["exact_graph"],
                    "exact_typed_graphs": totals["exact_typed_graph"],
                    "cases": per_case,
                }
    return report


if __name__ == "__main__":
    data = score(HERE / "outputs/f3f4_paired_results.tar.gz")
    out = HERE / "outputs/f3f4_paired_score.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({s: {a: {k: v for k, v in r.items() if k != "cases"}
                          for a, r in arms.items()} for s, arms in data.items()}, ensure_ascii=False))

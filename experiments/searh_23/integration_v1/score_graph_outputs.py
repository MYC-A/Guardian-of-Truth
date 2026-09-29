"""Score already recorded graph arms without invoking any model.

The W1 scorer returns nested counts; this script keeps the frozen casewise
errors and aggregates the two arms from the same gold file.
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "step1_working_v1"))
from w1_score import score_case


def score(archive: Path) -> dict:
    gold = json.loads((HERE / "frozen/graph_gold.json").read_text(encoding="utf-8"))
    result = {}
    with tarfile.open(archive, "r:gz") as saved:
        for arm in ("baseline", "scope_guard"):
            counts = {"correct_unique": 0, "extra_strict": 0,
                      "missing_directed": 0, "typed_unique": 0,
                      "exact_graph": 0, "exact_typed_graph": 0}
            cases = {}
            for case in gold:
                member = f"experiments/searh_23/integration_v1/outputs/{arm}/W1_DOWN10_LLM_SG/{case['case_id']}.json"
                data = json.load(saved.extractfile(member))
                row = score_case(case, data)
                cases[case["case_id"]] = row
                for key in counts:
                    counts[key] += row["counts"].get(key, 0)
            tp, fp, fn = (counts[k] for k in ("correct_unique", "extra_strict", "missing_directed"))
            result[arm] = {
                "correct": tp, "extra": fp, "missing": fn,
                "precision": tp / (tp + fp) if tp + fp else 0.0,
                "recall": tp / (tp + fn) if tp + fn else 0.0,
                "typed": counts["typed_unique"],
                "exact_graphs": counts["exact_graph"],
                "exact_typed_graphs": counts["exact_typed_graph"],
                "cases": cases,
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=HERE / "outputs/graph_remote_artifacts.tar.gz")
    parser.add_argument("--out", type=Path, default=HERE / "outputs/graph_followup_score.json")
    args = parser.parse_args()
    data = score(args.archive)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({arm: {k: v for k, v in row.items() if k != "cases"}
                      for arm, row in data.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

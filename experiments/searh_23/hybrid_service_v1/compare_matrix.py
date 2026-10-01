"""Paired graph × Φ comparison across two complete frozen campaign runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from score_campaign import (DATA, _family_bootstrap_delta,
                            _metrics, score as score_campaign)

SLOTS = {"M00": "g0-direct", "M10": "g3-ge-gp-surface",
         "M01": "m01-phi", "M11": "m11-ge-gp-phi"}


def _load_records(directory: Path):
    score_campaign(directory)  # ensures complete prediction set before gold
    config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in
        (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    by_arm = {}
    for record in records:
        by_arm.setdefault(record["config_id"], {})[record["case_id"]] = record
    return config, by_arm


def compare(graph_dir: Path, formal_dir: Path):
    graph_config, graph = _load_records(graph_dir)
    formal_config, formal = _load_records(formal_dir)
    if (graph_config["split"] != formal_config["split"] or
            graph_config["input_sha256"] != formal_config["input_sha256"] or
            graph_config["case_ids"] != formal_config["case_ids"]):
        raise ValueError("graph and formal runs use different cases")
    split = graph_config["split"]
    gold = {r["id"]: r for r in map(json.loads,
        (DATA / f"{split}_gold.jsonl").read_text(encoding="utf-8").splitlines())}
    ids = graph_config["case_ids"]
    combined = {**graph, **formal}
    for slot, arm in SLOTS.items():
        if arm not in combined or set(combined[arm]) != set(ids):
            raise ValueError(f"missing/incomplete matrix slot {slot}")
    matrix = {}
    for slot, arm in SLOTS.items():
        cases = combined[arm]
        pairs = [(gold[cid]["label"], int(cases[cid]["decision"] == "ERROR"))
                 for cid in ids]
        matrix[slot] = {"arm": arm, **_metrics(pairs),
                        "unknown": sum(cases[cid]["decision"] == "UNKNOWN"
                                       for cid in ids),
                        "calls": sum((cases[cid]["usage"] or {}).get("calls", 0)
                                     for cid in ids),
                        "tokens": sum((cases[cid]["usage"] or {}).get("tokens", 0)
                                      for cid in ids)}
    baseline = combined[SLOTS["M00"]]
    paired = {}
    for slot in ("M10", "M01", "M11"):
        candidate = combined[SLOTS[slot]]
        recovered, harmed = [], []
        for cid in ids:
            y = gold[cid]["label"]
            first = int(baseline[cid]["decision"] == "ERROR")
            next_ = int(candidate[cid]["decision"] == "ERROR")
            if first != y and next_ == y:
                recovered.append(cid)
            elif first == y and next_ != y:
                harmed.append(cid)
        paired[slot] = {"recovered": recovered, "harmed": harmed,
                        **_family_bootstrap_delta(gold, baseline, candidate, ids)}
    result = {"schema": "graph-phi-matrix/1", "split": split,
              "n": len(ids), "graph_run": str(graph_dir),
              "formal_run": str(formal_dir),
              "warning": ("GP is a source-preserving surface graph, not a "
                          "complete semantic policy graph. Φ is a bounded "
                          "model translation with unverified meaning."),
              "matrix": matrix, "paired_vs_M00": paired,
              "f1_interaction": round(matrix["M11"]["f1"] - matrix["M10"]["f1"] -
                                      matrix["M01"]["f1"] + matrix["M00"]["f1"], 4)}
    (formal_dir / "matrix_score.json").write_text(json.dumps(
        result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_dir", type=Path)
    parser.add_argument("formal_dir", type=Path)
    args = parser.parse_args()
    report = compare(args.graph_dir, args.formal_dir)
    print(json.dumps({"matrix": report["matrix"],
                      "paired_vs_M00": report["paired_vs_M00"],
                      "f1_interaction": report["f1_interaction"]},
                     ensure_ascii=False, indent=2))

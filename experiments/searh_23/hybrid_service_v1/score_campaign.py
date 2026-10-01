"""Independent scorer; open gold only after a complete frozen campaign."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "dataset" / "fresh_v1"


def _metrics(pairs):
    tp = sum(y == 1 and p == 1 for y, p in pairs)
    fp = sum(y == 0 and p == 1 for y, p in pairs)
    fn = sum(y == 1 and p == 0 for y, p in pairs)
    tn = sum(y == 0 and p == 0 for y, p in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall else 0.0}


def score(directory: Path):
    config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED" or summary["state"] != "SUCCEEDED":
        raise ValueError("refusing to open gold for an incomplete run")
    split = config["split"]
    gold_file = DATA / f"{split}_gold.jsonl"
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    import hashlib
    if hashlib.sha256(gold_file.read_bytes()).hexdigest() != (
            manifest["splits"][split]["gold_sha256"]):
        raise ValueError("gold hash mismatch")
    gold = {r["id"]: r for r in map(json.loads,
            gold_file.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in
               (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    by_arm = defaultdict(dict)
    for rec in records:
        if rec["status"] != "COMPLETED":
            continue
        arm, case_id = rec["config_id"], rec["case_id"]
        if case_id in by_arm[arm]:
            raise ValueError("duplicate prediction")
        by_arm[arm][case_id] = rec
    expected_ids = set(config["case_ids"])
    report = {"run_id": config["schema"] + ":" + status["run_id"],
              "split": split, "n": len(expected_ids), "arms": {},
              "paired": {}}
    for arm in config["config_sha256"]:
        items = by_arm[arm]
        if set(items) != expected_ids:
            raise ValueError(f"incomplete {arm}: {len(items)}/{len(expected_ids)}")
        pairs = [(gold[cid]["label"],
                  1 if items[cid]["decision"] == "ERROR" else 0)
                 for cid in config["case_ids"]]
        family_pairs = defaultdict(list)
        for cid, pair in zip(config["case_ids"], pairs):
            family_pairs[gold[cid]["policy_family_id"]].append(pair)
        family_metrics = {k: _metrics(v) for k, v in family_pairs.items()}
        unknown = sum(items[cid]["decision"] == "UNKNOWN"
                      for cid in expected_ids)
        report["arms"][arm] = {
            **_metrics(pairs), "unknown": unknown,
            "coverage": round((len(pairs) - unknown) / len(pairs), 4),
            "macro_family_f1": round(sum(m["f1"] for m in family_metrics.values())
                                     / len(family_metrics), 4),
            "by_family": family_metrics,
            "calls": sum((items[cid]["usage"] or {}).get("calls", 0)
                         for cid in expected_ids),
            "tokens": sum((items[cid]["usage"] or {}).get("tokens", 0)
                          for cid in expected_ids),
            "mean_elapsed_s": round(sum(items[cid]["elapsed_s"]
                                        for cid in expected_ids) / len(pairs), 3),
        }
    baseline = by_arm.get("g0-direct")
    if baseline:
        for arm, items in by_arm.items():
            if arm == "g0-direct":
                continue
            recovered, harmed, same_wrong = [], [], []
            for cid in config["case_ids"]:
                label = gold[cid]["label"]
                before = int(baseline[cid]["decision"] == "ERROR")
                after = int(items[cid]["decision"] == "ERROR")
                if before != label and after == label:
                    recovered.append(cid)
                elif before == label and after != label:
                    harmed.append(cid)
                elif before != label and after != label:
                    same_wrong.append(cid)
            report["paired"][arm] = {
                "recovered": recovered, "harmed": harmed,
                "same_wrong": same_wrong}
    out = directory / "score.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    report = score(args.directory)
    print(json.dumps({"run_id": report["run_id"],
                      "arms": {k: {x: v[x] for x in
                                   ("tp", "fp", "fn", "tn", "f1",
                                    "unknown", "calls", "tokens")}
                               for k, v in report["arms"].items()}},
                     ensure_ascii=False, indent=2))

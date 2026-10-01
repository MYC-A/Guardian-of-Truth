"""Post-run diagnostic of bounded Φ coverage, not an end-to-end verdict."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from score_campaign import DATA, _metrics, _quantile


def score(directory: Path):
    config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED":
        raise ValueError("refusing to open gold before complete formal run")
    split = config["split"]
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    gold_file = DATA / f"{split}_gold.jsonl"
    if hashlib.sha256(gold_file.read_bytes()).hexdigest() != manifest["splits"][split]["gold_sha256"]:
        raise ValueError("gold hash mismatch")
    if config["input_sha256"] != manifest["splits"][split]["input_sha256"]:
        raise ValueError("frozen input mismatch")
    gold = {r["id"]: r for r in map(json.loads,
        gold_file.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in
        (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = config["case_ids"]
    if len(set(ids)) != len(ids) or [r["id"] for r in records] != ids:
        raise ValueError("incomplete, duplicate or reordered formal records")
    if any(r["run_id"] != status["run_id"] for r in records):
        raise ValueError("run ID mismatch")
    by_relation = defaultdict(list)
    by_family = defaultdict(list)
    pairs, covered_pairs, uncovered, errors = [], [], [], []
    for record in records:
        cid = record["id"]
        label = gold[cid]["label"]
        relation = record["relation"]
        if relation not in ("FOLLOWS", "CONTRADICTS", "INSUFFICIENT"):
            raise ValueError("unexpected formal relation")
        # Conservative fallback is only for diagnostic classification metrics.
        prediction = int(relation == "CONTRADICTS")
        pair = label, prediction
        pairs.append(pair)
        by_relation[relation].append(cid)
        by_family[gold[cid]["policy_family_id"]].append(pair)
        if relation == "INSUFFICIENT":
            uncovered.append(cid)
        else:
            covered_pairs.append(pair)
        if relation != "INSUFFICIENT" and prediction != label:
            errors.append({"id": cid, "relation": relation,
                           "gold": label, "prediction": prediction,
                           "reason": record["reason"]})
    families = {name: _metrics(group) for name, group in by_family.items()}
    result = {"run_id": status["run_id"], "split": split, "n": len(ids),
        "warning": ("Formal relation is relative to an unverified model translation. "
                    "Correct backend execution does not certify policy completeness."),
        "mapping": "CONTRADICTS=>ERROR, FOLLOWS=>NO_ERROR, INSUFFICIENT=>UNKNOWN",
        "fallback_for_diagnostic_f1": "UNKNOWN=>NO_ERROR",
        "coverage": round(len(covered_pairs) / len(ids), 4),
        "translation_valid": sum(r["status"] == "VALID" for r in records),
        "relations": {key: len(value) for key, value in by_relation.items()},
        "uncovered_ids": uncovered, "covered_errors": errors,
        "all_cases_with_fallback": _metrics(pairs),
        "conditional_covered": _metrics(covered_pairs),
        "by_family": families,
        "macro_family_f1": round(sum(v["f1"] for v in families.values()) / len(families), 4),
        "calls": sum(r["usage"]["calls"] for r in records),
        "tokens": sum(r["usage"]["tokens"] for r in records),
        "latency_p50_s": _quantile([r["elapsed_s"] for r in records], .5),
        "latency_p95_s": _quantile([r["elapsed_s"] for r in records], .95)}
    (directory / "score.json").write_text(json.dumps(result,
        ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    report = score(parser.parse_args().directory)
    print(json.dumps({key: report[key] for key in
        ("run_id", "n", "coverage", "translation_valid", "relations",
         "all_cases_with_fallback", "conditional_covered", "calls", "tokens")},
        ensure_ascii=False, indent=2))

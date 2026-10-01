"""Post-run scorer for native support checkers on the frozen candidate bank.

This diagnostic maps unsupported (<0.5) to ERROR only to expose whether a
checker can distinguish each constructed pair. It is not a service verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from candidate_bank import BANK, DATA
from score_campaign import _metrics, _quantile


def score(directory: Path) -> dict:
    config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED":
        raise ValueError("refusing to open gold before complete run")
    split = config["split"]
    bank_file = BANK / f"{split}.jsonl"
    bank_manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(bank_file.read_bytes()).hexdigest() != config["bank_sha256"]:
        raise ValueError("candidate bank changed since run")
    if config["bank_sha256"] != bank_manifest["splits"][split]["sha256"]:
        raise ValueError("candidate bank manifest mismatch")
    gold_file = DATA / f"{split}_gold.jsonl"
    gold_manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(gold_file.read_bytes()).hexdigest() != gold_manifest["splits"][split]["gold_sha256"]:
        raise ValueError("gold manifest mismatch")
    gold = {row["id"]: row for row in map(json.loads,
        gold_file.read_text(encoding="utf-8").splitlines())}
    bank = {row["id"]: row for row in map(json.loads,
        bank_file.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in
        (directory / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = config["case_ids"]
    if len(ids) != len(set(ids)) or [r["id"] for r in records] != ids:
        raise ValueError("missing, duplicate or out-of-order scores")
    if not set(ids) <= gold.keys() or not set(ids) <= bank.keys():
        raise ValueError("score ID absent from frozen bank or gold")
    for row in records:
        if row["run_id"] != status["run_id"]:
            raise ValueError("run ID mismatch")
        if row["status"] == "VALID" and not (
                isinstance(row["support_score"], (int, float)) and
                0 <= row["support_score"] <= 1):
            raise ValueError("invalid support score")

    by_kind: dict[str, list[tuple[int, int]]] = defaultdict(list)
    by_family: dict[str, list[tuple[int, int]]] = defaultdict(list)
    all_pairs = []
    valid_pairs = []
    invalid = []
    misses = []
    for row in records:
        cid = row["id"]
        label = gold[cid]["label"]
        valid = row["status"] == "VALID"
        # Frozen conservative diagnostic fallback: invalid => NO_ERROR.
        prediction = int(valid and row["support_score"] < config["threshold"])
        pair = (label, prediction)
        all_pairs.append(pair)
        by_kind[bank[cid]["claim_kind"]].append(pair)
        by_family[gold[cid]["policy_family_id"]].append(pair)
        if valid:
            valid_pairs.append(pair)
        else:
            invalid.append(cid)
        if prediction != label:
            misses.append({"id": cid, "gold": label, "prediction": prediction,
                           "score": row["support_score"], "valid": valid,
                           "claim_kind": bank[cid]["claim_kind"],
                           "policy_family_id": gold[cid]["policy_family_id"]})
    family_scores = {key: _metrics(pairs) for key, pairs in by_family.items()}
    result = {"run_id": status["run_id"], "model": config["model"],
              "split": split, "n": len(ids), "threshold": config["threshold"],
              "diagnostic_mapping": "support_score < threshold => ERROR",
              "invalid_fallback": "NO_ERROR",
              "warning": "Native support is not a Guardian error verdict; some accurate uncertainty claims have no positive source entailment.",
              "coverage": round(len(valid_pairs) / len(ids), 4),
              "invalid_ids": invalid,
              "all_cases": _metrics(all_pairs),
              "conditional_valid": _metrics(valid_pairs),
              "by_kind": {key: _metrics(pairs) for key, pairs in by_kind.items()},
              "by_family": family_scores,
              "macro_family_f1": round(sum(v["f1"] for v in family_scores.values()) /
                                       len(family_scores), 4),
              "latency_p50_s": _quantile([r["elapsed_s"] for r in records], .5),
              "latency_p95_s": _quantile([r["elapsed_s"] for r in records], .95),
              "misses": misses}
    (directory / "score.json").write_text(json.dumps(result, ensure_ascii=False,
        indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    result = score(parser.parse_args().directory)
    print(json.dumps({key: result[key] for key in
        ("run_id", "model", "split", "n", "coverage", "all_cases",
         "conditional_valid", "by_kind", "macro_family_f1",
         "latency_p50_s", "latency_p95_s")}, ensure_ascii=False,
        indent=2))

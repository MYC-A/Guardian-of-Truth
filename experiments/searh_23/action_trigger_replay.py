"""Replay frozen model checks through source-anchored action triggers."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from action_trigger_v1 import audit_broken as audit_scope
from call_scope_replay import replay as verify_sealed_replay
from temporal_counterevidence_v1 import audit_broken as audit_temporal


def replay(directory: Path, *, layer: str = "scope") -> dict:
    if layer not in {"scope", "temporal"}:
        raise ValueError("unknown replay layer")
    auditor = audit_scope if layer == "scope" else audit_temporal
    prior = verify_sealed_replay(directory / "input.json",
                                 directory / "predictions.jsonl",
                                 directory / "score.json")
    frozen = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    score = json.loads((directory / "score.json").read_text(encoding="utf-8"))
    source_by_id = {item["id"]: item for item in frozen["inputs"]}
    counts = Counter()
    cases = []
    for row in score["per_case"]:
        decision = auditor({"verdict": row["raw"], "checks": row["checks"]},
                           source_by_id[row["id"]])
        verdict, gold = decision["verdict"], row["gold"]
        category = ("TP" if gold else "FP") if verdict == "VIOLATION" else (
            "FN" if gold else "TN") if verdict == "SAFE" else (
            "UNKNOWN_POS" if gold else "UNKNOWN_NEG")
        counts[category] += 1
        cases.append({"id": row["id"], "gold": gold, "raw": row["raw"],
                      **decision})
    return {"schema_version": "action-trigger-replay-v1", "layer": layer,
            "source_seal": prior["source_seal"],
            "scope": "viewed authored cases; withdrawn accusations are UNKNOWN, not safe",
            "counts": {key: counts[key] for key in
                       ("TP", "FP", "FN", "TN", "UNKNOWN_POS", "UNKNOWN_NEG")},
            "per_case": cases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--layer", choices=("scope", "temporal"), default="scope")
    args = parser.parse_args()
    report = replay(args.dir, layer=args.layer)
    output = args.dir / ("action_trigger_replay.json" if args.layer == "scope"
                         else "temporal_counterevidence_replay.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report["counts"]))


if __name__ == "__main__":
    main()

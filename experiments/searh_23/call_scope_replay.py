"""Replay a conservative policy-scope audit on sealed call-probe predictions.

This script does not call a model. The development gold remains unchanged; a
removed unsupported accusation becomes UNKNOWN rather than a claim of safety.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from call_scope_v1 import scoped_verdict


def replay(input_path: Path, predictions_path: Path, score_path: Path) -> dict:
    frozen = json.loads(input_path.read_text(encoding="utf-8"))
    score = json.loads(score_path.read_text(encoding="utf-8"))
    seal = score["seal"]
    # Git may check out the tracked JSON with CRLF on Windows. The Linux
    # inference seal covers the equivalent LF bytes.
    normalized_input = input_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_input).hexdigest() != seal["frozen_sha256"]:
        raise ValueError("frozen input differs from scored artifact")
    normalized_predictions = predictions_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_predictions).hexdigest() != seal["predictions_sha256"]:
        raise ValueError("predictions differ from scored artifact")
    inputs = {item["id"]: item for item in frozen["inputs"]}
    rows = score["per_case"]
    if list(inputs) != [row["id"] for row in rows]:
        raise ValueError("scored IDs differ from frozen inputs")
    counts = Counter()
    cases = []
    for row in rows:
        decision = scoped_verdict({"verdict": row["raw"], "checks": row["checks"]},
                                  inputs[row["id"]])
        verdict = decision["verdict"]
        gold = row["gold"]
        category = ("TP" if gold else "FP") if verdict == "VIOLATION" else (
            "FN" if gold else "TN") if verdict == "SAFE" else (
            "UNKNOWN_POS" if gold else "UNKNOWN_NEG")
        counts[category] += 1
        cases.append({"id": row["id"], "gold": gold, "raw": row["raw"],
                      "scope": verdict, **decision})
    return {"schema_version": "call-scope-replay-v1",
            "interpretation": "viewed authored development cases; UNKNOWN needs a separate fallback",
            "source_seal": seal, "counts": {key: counts[key] for key in
            ("TP", "FP", "FN", "TN", "UNKNOWN_POS", "UNKNOWN_NEG")},
            "per_case": cases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.dir / "scope_replay.json"
    report = replay(args.dir / "input.json", args.dir / "predictions.jsonl",
                    args.dir / "score.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report["counts"]))


if __name__ == "__main__":
    main()

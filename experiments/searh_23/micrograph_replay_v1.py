"""Seal label-free micrograph decisions, then score frozen controls separately."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from micrograph_certificate_v1 import analyze


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/searh_23/micrograph_controls_v1"
CONTROLS = ROOT / "experiments/searh_23/micrograph_controls_v1"


def input_path(suite: str) -> Path:
    if suite.startswith("parcel_"):
        return ROOT / "outputs/searh_23/call_condition_probe" / suite / "input.json"
    return OUT / suite / "input.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run(suite: str) -> dict:
    folder = OUT / suite
    folder.mkdir(parents=True, exist_ok=True)
    frozen = input_path(suite)
    data = json.loads(frozen.read_text(encoding="utf-8"))
    if suite in {"repair", "repair_renamed"}:
        manifest = json.loads((CONTROLS / suite / "manifest.json").read_text(encoding="utf-8"))
        if digest(frozen) != manifest["input_sha256_lf"]:
            raise ValueError("frozen input changed")
    rows = [{"id": item["id"], "input_sha256": item["input_sha256"],
             "analysis": analyze(item)} for item in data["inputs"]]
    predictions = folder / "micrograph_predictions.json"
    payload = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if predictions.exists() and predictions.read_bytes().replace(b"\r\n", b"\n") != payload:
        raise ValueError("sealed predictions differ")
    predictions.write_bytes(payload)
    seal = {"suite": suite, "input_sha256_lf": digest(frozen),
            "predictions_sha256_lf": digest(predictions),
            "ids": [row["id"] for row in rows]}
    seal_path = folder / "micrograph_prediction_seal.json"
    seal_bytes = (json.dumps(seal, indent=2) + "\n").encode("utf-8")
    if seal_path.exists() and seal_path.read_bytes().replace(b"\r\n", b"\n") != seal_bytes:
        raise ValueError("prediction seal differs")
    seal_path.write_bytes(seal_bytes)
    return seal


def score(suite: str) -> dict:
    folder = OUT / suite
    seal = json.loads((folder / "micrograph_prediction_seal.json").read_text(encoding="utf-8"))
    if digest(input_path(suite)) != seal["input_sha256_lf"] or digest(folder / "micrograph_predictions.json") != seal["predictions_sha256_lf"]:
        raise ValueError("sealed artifact changed")
    rows = json.loads((folder / "micrograph_predictions.json").read_text(encoding="utf-8"))
    if [row["id"] for row in rows] != seal["ids"]:
        raise ValueError("prediction order changed")
    if suite in {"repair", "repair_renamed"}:
        gold_path = CONTROLS / suite / "expected.json"
    elif suite in {"parcel_v1", "parcel_v1_renamed"}:
        gold_path = ROOT / "experiments/searh_23/parcel_trigger_v1" / suite / "expected.json"
    else:
        raise ValueError("unsupported suite")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    counts = dict(TP=0, FP=0, FN=0, TN=0, UNKNOWN_POS=0, UNKNOWN_NEG=0)
    per_case = []
    for row in rows:
        expected = gold[row["id"]]
        verdict = row["analysis"]["verdict"]
        if verdict == "UNKNOWN":
            bucket = "UNKNOWN_POS" if expected else "UNKNOWN_NEG"
        elif verdict == "VIOLATION":
            bucket = "TP" if expected else "FP"
        else:
            bucket = "FN" if expected else "TN"
        counts[bucket] += 1
        per_case.append({"id": row["id"], "gold": expected, "verdict": verdict,
                         "bucket": bucket, "checks": row["analysis"]["checks"],
                         "errors": row["analysis"]["errors"]})
    report = {"suite": suite, "scope": "bounded authored controls; not independent contest accuracy",
              "seal": seal, "counts": counts, "per_case": per_case}
    (folder / "micrograph_score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("suite", choices=("repair", "repair_renamed", "parcel_v1", "parcel_v1_renamed"))
    args = parser.parse_args()
    print(json.dumps(run(args.suite) if args.phase == "run" else score(args.suite).get("counts"),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

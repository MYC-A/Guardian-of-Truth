"""Frozen response-only mode probe; exact source spans and per-case errors.

Predictions are produced using inputs only; gold is read after all calls.
This probes claim inventory/mode, not predicate binding or Guardian verdicts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE.parent / "operation_check"))

from guardian_truth.integration.claim_modes import SYSTEM_PROMPT, validate_claim_proposal
from oc_common import Mistral

FROZEN = HERE / "frozen" / "trajectories_v1"


def run(split: str) -> dict:
    inputs = json.loads((FROZEN / f"{split}_inputs.json").read_text(encoding="utf-8"))
    client = Mistral(cache_dir=HERE / "outputs" / "step3_mode_cache")
    by_response: dict[str, dict] = {}
    predictions: dict[str, dict] = {}
    for row in inputs:
        response = row["target_response"]["text"]
        if response not in by_response:
            rec = client.ask(SYSTEM_PROMPT,
                             json.dumps({"assistant_reply": response}, ensure_ascii=False),
                             max_tokens=768)
            parsed, issues = validate_claim_proposal(response, rec["raw"])
            by_response[response] = {
                "claims": [item.as_dict() for item in parsed],
                "issues": list(issues), "raw": rec["raw"],
                "usage": rec.get("usage", {}), "served_model": rec.get("served_model"),
                "finish_reason": rec.get("finish_reason")}
        predictions[row["case_id"]] = by_response[response]

    gold = {row["case_id"]: row for row in json.loads(
        (FROZEN / f"{split}_gold.json").read_text(encoding="utf-8"))}
    counts = Counter()
    per_case = []
    for row in inputs:
        cid = row["case_id"]
        proposed = predictions[cid]
        pred = {(x["start"], x["end"], x["mode"]) for x in proposed["claims"]}
        truth = {(x["start"], x["end"], x["mode"]) for x in gold[cid]["claims"]}
        tp, fp, fn = pred & truth, pred - truth, truth - pred
        counts.update({"correct": len(tp), "extra": len(fp), "missing": len(fn),
                       "predicted": len(pred), "gold": len(truth),
                       "cases_exact": int(not fp and not fn)})
        per_case.append({"case_id": cid, "correct": len(tp), "extra": len(fp),
                         "missing": len(fn), "predicted": proposed["claims"],
                         "gold": gold[cid]["claims"], "issues": proposed["issues"]})
    report = {"split": split, "track": "response-only source-exact claim modes",
              "model": client.model, "unique_responses": len(by_response),
              "api_calls": client.calls, "usage": client.usage_total,
              "counts": dict(counts),
              "precision": round(counts["correct"] / max(1, counts["predicted"]), 4),
              "recall": round(counts["correct"] / max(1, counts["gold"]), 4),
              "per_case": per_case,
              "raw_by_response": by_response}
    out = HERE / "outputs" / f"step3_modes_{split}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"per_case", "raw_by_response"}}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "sealed"), default="dev")
    args = parser.parse_args()
    run(args.split)

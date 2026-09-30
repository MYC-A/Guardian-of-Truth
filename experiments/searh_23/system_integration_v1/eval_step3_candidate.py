"""Dev-only candidate-centred Step 3 mode probe.

This run follows the first sealed mode result, so it is a development
iteration and cannot claim held-out transfer on trajectories_v1/sealed.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE.parent / "operation_check"))

from guardian_truth.integration.candidate_claims import (
    SYSTEM_PROMPT, candidate_meanings, validate_proposal)
from oc_common import Mistral
from eval_step2_documented import as_case

FROZEN = HERE / "frozen" / "trajectories_v1"


def run() -> dict:
    rows = json.loads((FROZEN / "dev_inputs.json").read_text(encoding="utf-8"))
    client = Mistral(cache_dir=HERE / "outputs" / "step3_candidate_cache")
    predictions: dict[str, dict] = {}
    for row in rows:
        response = row["target_response"]["text"]
        candidates = candidate_meanings(as_case(row))
        query = {"assistant_reply": response,
                 "candidates": [c.as_dict() for c in candidates]}
        record = client.ask(SYSTEM_PROMPT, json.dumps(query, ensure_ascii=False),
                            max_tokens=1200)
        accepted, issues = validate_proposal(response, candidates, record["raw"])
        predictions[row["case_id"]] = {
            "candidates": [c.as_dict() for c in candidates],
            "accepted": list(accepted), "issues": list(issues),
            "raw": record["raw"], "usage": record.get("usage", {})}
    gold = {r["case_id"]: r for r in json.loads(
        (FROZEN / "dev_gold.json").read_text(encoding="utf-8"))}
    counts = Counter()
    per_case = []
    for row in rows:
        cid = row["case_id"]
        pred = predictions[cid]
        pk = {(x["predicate"], x["mode"]) for x in pred["accepted"]
              if x["mode"] not in {"NONE", "UNKNOWN"}}
        gk = {(x["predicate"], x["mode"]) for x in gold[cid]["claims"]}
        tp, fp, fn = pk & gk, pk - gk, gk - pk
        counts.update({"correct": len(tp), "extra": len(fp),
                       "missing": len(fn), "gold": len(gk),
                       "predicted": len(pk), "cases_exact": int(not fp and not fn)})
        per_case.append({"case_id": cid, "correct": len(tp),
                         "extra": [list(x) for x in sorted(fp)],
                         "missing": [list(x) for x in sorted(fn)],
                         "prediction": pred, "gold": gold[cid]["claims"]})
    report = {"split": "dev", "track": "post-sealed candidate-centred development",
              "model": client.model, "api_calls": client.calls,
              "usage": client.usage_total, "counts": dict(counts),
              "precision": round(counts["correct"] / max(1, counts["predicted"]), 4),
              "recall": round(counts["correct"] / max(1, counts["gold"]), 4),
              "per_case": per_case}
    out = HERE / "outputs" / "step3_candidate_dev.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    run()

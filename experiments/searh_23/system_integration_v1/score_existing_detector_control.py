"""Score archived old-detector audits; binary fallback is UNKNOWN in research."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen" / "trajectories_v1"
OUT = HERE / "outputs"


def run(split: str) -> dict:
    inputs = [json.loads(line) for line in (OUT / f"existing_detector_{split}_inputs.jsonl")
              .read_text(encoding="utf-8").splitlines() if line.strip()]
    audits = [json.loads(line) for line in (OUT / f"existing_detector_{split}_audit.jsonl")
              .read_text(encoding="utf-8").splitlines() if line.strip()]
    gold = {x["case_id"]: x["verdict"] for x in json.loads(
        (FROZEN / f"{split}_gold.json").read_text(encoding="utf-8"))}
    ids = [x["id"] for x in inputs]
    if (len(ids) != len(set(ids)) or len(audits) != len(ids)
            or [x["id"] for x in audits] != ids or set(ids) != set(gold)):
        raise ValueError("incomplete or reordered baseline run")
    per_case = []
    counts = Counter()
    usage = Counter()
    for row in audits:
        cid = row["id"]
        expected = gold[cid]
        predicted = ("UNKNOWN" if row["used_fallback"] else
                     "ERROR" if row["label"] == 1 else "NO_ERROR")
        decided = predicted != "UNKNOWN"
        counts.update({"total": 1, "correct": int(predicted == expected),
                       "decided": int(decided),
                       "decided_correct": int(decided and predicted == expected),
                       "pred_" + predicted: 1, "gold_" + expected: 1,
                       "error_caught": int(expected == "ERROR" and predicted == "ERROR"),
                       "error_hidden_unknown": int(expected == "ERROR" and
                                                   predicted == "UNKNOWN"),
                       "error_missed_as_no_error": int(expected == "ERROR" and
                                                       predicted == "NO_ERROR"),
                       "no_error_caught": int(expected == "NO_ERROR" and
                                              predicted == "NO_ERROR"),
                       "false_error": int(expected != "ERROR" and
                                          predicted == "ERROR")})
        per_case.append({"id": cid, "expected": expected, "predicted": predicted,
                         "reason": row["reason"], "score": row.get("score"),
                         "mechanical_status": row.get("status")})
        usage.update({k: int(row.get("semantic_usage", {}).get(k, 0) or 0)
                      for k in ("llm_calls", "prompt_tokens", "completion_tokens",
                                "total_tokens")})
    metrics = {"coverage": counts["decided"] / counts["total"],
               "accuracy_when_decided": (counts["decided_correct"] /
                                         counts["decided"] if counts["decided"] else None),
               "error_recall": (counts["error_caught"] / counts["gold_ERROR"]
                                if counts["gold_ERROR"] else None),
               "no_error_recall": (counts["no_error_caught"] / counts["gold_NO_ERROR"]
                                   if counts["gold_NO_ERROR"] else None),
               "unknown_rate": counts["pred_UNKNOWN"] / counts["total"]}
    report = {"split": split, "track": "existing_predict_graph_mistral",
              "counts": dict(counts), "metrics": metrics,
              "usage": dict(usage),
              "run_report": json.loads((OUT / f"existing_detector_{split}_run.json")
                                       .read_text(encoding="utf-8")),
              "per_case": per_case}
    (OUT / f"existing_detector_{split}_score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"dev", "sealed"}:
        raise SystemExit("usage: score_existing_detector_control.py dev|sealed")
    run(sys.argv[1])

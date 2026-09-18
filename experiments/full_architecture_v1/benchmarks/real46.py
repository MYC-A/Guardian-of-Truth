"""full_architecture_v1 — real46 benchmark runner (directive §22).

Gold firewall discipline:
  1. inference over (id, prompt, response) ONLY + the frozen frontend
     snapshot (phi.jsonl) — labels never loaded during prediction;
  2. per case: frontend hash, NeutralCoreInput hash, interpretation stats,
     world verdicts, solver notes, certificate digest + checker verdict,
     binary output — all persisted BEFORE any label is touched;
  3. only after the prediction set is frozen: load labels, compute
     TP/FP/FN/TN, precision, recall, F1 (this module's score()).

Leak audit: no gold_label/label/expected_* symbol is imported or referenced
in the inference path (automated scan in the hardcoding audit).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH),
          str(_REPO / "src"), str(_FULLARCH.parent / "semantic_pipeline_v1")):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline import ARMS, load_phi_row, run_arm  # noqa: E402

PHI_PATH = _REPO / "outputs" / "vnext" / "semantic_pipeline_v1" / "phi.jsonl"
DEFAULT_INPUT = _REPO / "valid.parquet"
DEFAULT_OUT = _REPO / "outputs" / "full_architecture_v1" / "real46"


def load_cases(limit: int | None = None) -> list[dict]:
    import pyarrow.parquet as pq
    table = pq.read_table(DEFAULT_INPUT, columns=["id", "prompt", "response"])
    rows = table.to_pylist()
    if limit:
        rows = rows[:limit]
    return rows


def run_arm_all(arm: str, out_dir: Path, limit: int | None = None,
                resume: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / f"predictions__{arm}.jsonl"
    done: set[str] = set()
    if resume and predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["case_id"])
            except Exception:
                pass
    cases = load_cases(limit)
    todo = [case for case in cases if case["id"] not in done]
    print(f"[{arm}] {len(cases)} cases, {len(todo)} to run", flush=True)
    started = time.time()
    with predictions_path.open("a", encoding="utf-8") as handle:
        for index, case in enumerate(todo):
            phi_row = load_phi_row(PHI_PATH, case["id"])
            if phi_row is None:
                record = {"case_id": case["id"], "arm": arm,
                          "status": "FRONTEND_MISSING", "binary": 0,
                          "error": "no phi row for case"}
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                continue
            record = run_arm(case, phi_row, arm)
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
            handle.flush()
            if (index + 1) % 10 == 0:
                elapsed = time.time() - started
                print(f"[{arm}] {index + 1}/{len(todo)} "
                      f"({elapsed:.0f}s)", flush=True)
    return predictions_path


def score(predictions_path: Path) -> dict:
    """Load labels ONLY now (after predictions are frozen) and compute
    metrics.  Labels come from the parquet's label column — never from the
    inference path."""
    import pyarrow.parquet as pq
    table = pq.read_table(DEFAULT_INPUT, columns=["id", "label"])
    labels = {row["id"]: int(row["label"]) for row in table.to_pylist()}
    records = [json.loads(line) for line
               in predictions_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    tp = fp = fn = tn = 0
    unresolved = 0
    for record in records:
        label = labels.get(record["case_id"])
        if label is None:
            continue
        prediction = int(record.get("binary", 0))
        if record.get("status") == "UNRESOLVED":
            unresolved += 1
        if prediction == 1 and label == 1:
            tp += 1
        elif prediction == 1 and label == 0:
            fp += 1
        elif prediction == 0 and label == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"arm_records": len(records), "tp": tp, "fp": fp, "fn": fn,
            "tn": tn, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4),
            "unresolved_rate": round(unresolved / max(len(records), 1), 4)}


def main(arms: str = "N1,N2,N3,N4,N4-I,N5", limit: int | None = None,
         out_dir: Path | None = None, resume: bool = True,
         score_only: bool = False) -> None:
    out_dir = out_dir or DEFAULT_OUT
    selected = [arm.strip() for arm in arms.split(",") if arm.strip()]
    for arm in selected:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm} (available: {ARMS})")
    for arm in selected:
        if not score_only:
            predictions_path = run_arm_all(arm, out_dir, limit, resume)
        else:
            predictions_path = out_dir / f"predictions__{arm}.jsonl"
        if predictions_path.exists():
            metrics = score(predictions_path)
            print(f"[{arm}] metrics:", json.dumps(metrics), flush=True)
            (out_dir / f"metrics__{arm}.json").write_text(
                json.dumps(metrics, indent=1), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", default="N1,N2,N3,N4,N4-I,N5")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction,
                        default=True)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    main(args.arms, args.limit, args.output_dir, args.resume, args.score_only)

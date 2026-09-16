"""Run frozen B4h-sound-v2 on public competition inputs with a gold firewall."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.settings import load_env_file  # noqa: E402
from guardian_truth.vnext.integrity import canonical  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import build_live_backend  # noqa: E402
from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input  # noqa: E402
from guardian_truth.vnext.e2e.real_valid_v1 import (MODES, competition_view, run_mode, score,
    write_case_audit, write_predictions, write_premise_coverage)  # noqa: E402


def inference_records(path: Path) -> list[dict]:
    import pandas as pd
    frame = pd.read_parquet(path, columns=["id", "prompt", "response"])
    records = [competition_view(row) for row in frame.to_dict("records")]
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("duplicate competition id")
    return records


def gold_labels(path: Path) -> dict[str, int]:
    import pandas as pd
    frame = pd.read_parquet(path, columns=["id", "label"])
    return {row["id"]: int(row["label"]) for row in frame.to_dict("records")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "valid.parquet")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/vnext/real_valid")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=("bai", "groq"), default="groq")
    parser.add_argument("--model", default="qwen/qwen3.8-27b")
    parser.add_argument("--api-key-env", default="GROQ_API_KEY")
    parser.add_argument("--modes", default="R0,R1,R2")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cache-mode", choices=("cold", "warm", "resume"), default="resume")
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--reasoning-effort", choices=("none", "low", "medium", "high"),
                        default="none")
    args = parser.parse_args()
    args.input = args.input.resolve()
    args.output_dir = args.output_dir.resolve()
    args.env_file = args.env_file.resolve()

    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    if not modes or any(mode not in MODES for mode in modes):
        parser.error("modes must be a comma-separated subset of R0,R1,R2")
    records = inference_records(args.input)
    if args.limit is not None:
        records = records[:args.limit]
    adapted = [adapt_competition_input(record) for record in records]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_",
                     f"{args.provider}__{args.model}__mot{args.max_output_tokens}"
                     f"__reason-{args.reasoning_effort}")
    cache_path = args.output_dir / f"llm_cache__{run_tag}.json"
    if args.cache_mode == "cold" and cache_path.exists():
        parser.error("cold run requires an absent cache file")
    if not load_env_file(args.env_file):
        parser.error("env file not found")
    backend = build_live_backend(
        interval_seconds=args.interval_seconds,
        cache_path=cache_path if args.cache_mode != "cold" else None,
        provider=args.provider, model=args.model, api_key_env=args.api_key_env,
        max_output_tokens=args.max_output_tokens,
        reasoning_effort=None if args.reasoning_effort == "none" else args.reasoning_effort,
        fail_fast_error_categories=("rate_limit", "insufficient_user_quota", "quota"))
    if args.cache_mode == "cold":
        backend.cache_path = cache_path

    input_sha256 = hashlib.sha256(canonical(records)).hexdigest()
    run_config = {"provider": args.provider, "model": args.model,
                  "api_key_env": args.api_key_env, "cache_mode": args.cache_mode,
                  "max_output_tokens": args.max_output_tokens,
                  "reasoning_effort": args.reasoning_effort,
                  "cache_path": str(cache_path.relative_to(ROOT)),
                  "input_sha256": input_sha256, "rows": len(records), "modes": modes}
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2), encoding="utf-8")

    by_mode, seals = {}, {}
    for mode in modes:
        progress = args.output_dir / f"{mode}_audit__{run_tag}.json"
        rows = run_mode(adapted, backend, mode, progress)
        by_mode[mode] = rows
        prediction_path = args.output_dir / f"{mode}_predictions.csv"
        seals[mode] = {"path": str(prediction_path.relative_to(ROOT)),
                       "sha256": write_predictions(rows, prediction_path),
                       "rows": len(rows), "provider": args.provider,
                       "model": args.model, "input_sha256": input_sha256}
    (args.output_dir / "prediction_seals.json").write_text(
        json.dumps(seals, ensure_ascii=False, indent=2), encoding="utf-8")

    # Gold is loaded only after every requested prediction file is sealed.
    gold = gold_labels(args.input)
    metrics = {mode: score(rows, gold) for mode, rows in by_mode.items()}
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    write_case_audit(adapted, by_mode, args.output_dir / "cases.jsonl", gold=gold)
    write_premise_coverage(adapted, args.output_dir / "premise_coverage.csv")
    iterations = [{
        "iteration": 0,
        "commit": "315bee335a467476732b47e1e7f412097222cd3b",
        "root_cause": "BASELINE",
        "hypothesis": "frozen B4h-sound-v2 through a lossless competition adapter",
        "changed_files": ["competition_adapter_v1.py", "real_valid_v1.py",
                          "evaluate_real_valid.py"],
        "tests": ["tests/e2e", "tests/e2e_soundness"],
        "metrics_before": None,
        "metrics_after": metrics,
        "corrections": [],
        "regressions": [],
        "decision": "BASELINE",
    }]
    (args.output_dir / "iterations.json").write_text(
        json.dumps(iterations, ensure_ascii=False, indent=2), encoding="utf-8")
    backend.persist_receipts(args.output_dir / f"llm_receipts__{run_tag}.json")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

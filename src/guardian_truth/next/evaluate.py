"""Single reproducible entrypoint for Guardian Next experiments.

Examples:
    python -m guardian_truth.next.evaluate baseline --input valid.parquet
    python -m guardian_truth.next.evaluate policy --input valid.parquet
    python -m guardian_truth.next.evaluate claims --input valid.parquet
    python -m guardian_truth.next.evaluate internal --input valid.parquet

Reference labels are read only after each arm has produced its prediction.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector

from .claims import extract_claims
from .effects import schema_registry
from .monitor import review as next_review
from .normalize import build_evidence, normalize_trace
from .policy import compile_policy
from .statistics import hierarchical_bootstrap_delta, mcnemar_exact


DEFAULT_OUTPUTS = {
    "baseline": "baseline.json",
    "policy": "policy_arms.json",
    "model": "model_manifest.json",
    "tool": "tool_effect_arms.json",
    "claims": "claim_arms.json",
    "internal": "end_to_end_arms.json",
    "external": "external_results.json",
    "final": "final_manifest.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _metrics(labels: list[int], predictions: list[int]) -> dict[str, Any]:
    tp = sum(y == 1 and p == 1 for y, p in zip(labels, predictions))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, predictions))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, predictions))
    tn = sum(y == 0 and p == 0 for y, p in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n": len(labels), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "accuracy": (tp + tn) / len(labels) if labels else 0.0,
    }


def _metadata(input_path: Path, stage: str) -> dict[str, Any]:
    return {
        "schema_version": "guardian-next-eval-v1",
        "stage": stage,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _git("rev-parse", "HEAD"),
        "git_tree": _git("rev-parse", "HEAD^{tree}"),
        "python": sys.version,
        "platform": platform.platform(),
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "warning": "Development data; held-out independence is not established.",
    }


def _load(path: Path):
    rows = read_rows(path)
    validate_rows(rows)
    return rows


def _evaluate_arm(rows, predict: Callable[[str, str], tuple[int, dict]]) -> dict[str, Any]:
    predictions, traces = [], []
    started = time.perf_counter()
    for row in rows:
        # Blind boundary: only prompt and response cross into the arm.
        prediction, trace = predict(row["prompt"], row["response"])
        predictions.append(int(prediction))
        traces.append({"id": row["id"], **trace})
    labels = [int(row["label"]) for row in rows]
    return {**_metrics(labels, predictions), "seconds": time.perf_counter() - started,
            "predictions": predictions, "traces": traces}


def run_baseline(rows) -> dict[str, Any]:
    detector = Detector()

    def predict(prompt, response):
        result = detector.review(prompt, response)
        return int(result.status == "violation"), {
            "status": result.status,
            "finding_codes": [item.code for item in result.findings],
            "unknown": list(result.unresolved),
        }
    return {"arms": {"X0_CURRENT_V5_3": _evaluate_arm(rows, predict)}}


def run_policy(rows) -> dict[str, Any]:
    bundles = [compile_policy(row["prompt"], arm="P0") for row in rows]
    return {"arms": {"P0_CURRENT_EXACT": {
        "examples": len(bundles),
        "unique_policy_hashes": len({item.source_hash for item in bundles}),
        "rules": sum(len(item.rules) for item in bundles),
        "segments": sum(len(item.coverage) for item in bundles),
        "compiled_segments": sum(c.status == "compiled" for item in bundles for c in item.coverage),
        "unknown_segments": sum(c.status == "unknown" for item in bundles for c in item.coverage),
        "trace_independent": all(item.trace_independent for item in bundles),
    }}, "unavailable_arms": ["P1_DIRECT_LOCAL", "P2_TYPED_LOCAL", "P3_STRONG_TYPED",
                              "P4_CANDIDATE_ORACLE", "P5_PAIRWISE", "P6_MUTANTS"]}


def run_tool(rows) -> dict[str, Any]:
    registries = [schema_registry(row["prompt"]) for row in rows]
    contracts = [contract for registry in registries for contract in registry.values()]
    return {"arms": {"T0_SCHEMA_NAME": {
        "examples": len(rows),
        "contracts": len(contracts),
        "unique_tools": len({contract.tool for contract in contracts}),
        "guaranteed_effects": sum(len(contract.guaranteed_effects) for contract in contracts),
        "failure_no_effect_true": sum(contract.failure_no_effect.value == "true" for contract in contracts),
        "note": "Input schemas do not establish effects.",
    }}, "unavailable_arms": ["T1_HUMAN_GOLD", "T2_LLM", "T3_DOCS_TRACES_TESTS"]}


def run_claims(rows) -> dict[str, Any]:
    extracted, bindings = 0, {}
    per_example = []
    for row in rows:
        claims = extract_claims(row["response"])
        evidence = build_evidence(normalize_trace(row["prompt"], row["response"]))
        from .binder import bind_claims
        bound = bind_claims(claims, evidence)
        extracted += len(claims)
        for item in bound:
            bindings[item.status.value] = bindings.get(item.status.value, 0) + 1
        per_example.append({"id": row["id"], "claims": len(claims),
                            "kinds": [item.kind.value for item in claims]})
    return {"arms": {"C0_DETERMINISTIC_BLIND": {
        "examples": len(rows), "claims": extracted, "binding_statuses": bindings,
        "prompt_visible_to_extractor": False, "per_example": per_example,
    }}, "unavailable_arms": ["C1_LOCAL_TYPED", "C2_STRONG_TYPED"]}


def run_internal(rows) -> dict[str, Any]:
    baseline = run_baseline(rows)["arms"]["X0_CURRENT_V5_3"]

    def predict(prompt, response):
        result = next_review(prompt, response)
        return result.label, {"status": result.status.value, "used_fallback": result.used_fallback,
                              "claims": len(result.claims), "evidence": len(result.evidence)}
    proposed = _evaluate_arm(rows, predict)
    labels = [int(row["label"]) for row in rows]
    incumbent_predictions = baseline["predictions"]
    candidate_predictions = proposed["predictions"]
    groups = [str(row["id"]).split("::")[0] for row in rows]
    return {"arms": {"X0_CURRENT_V5_3": baseline, "X5_PROPOSED_MIN": proposed},
            "comparison": {"delta_f1": proposed["f1"] - baseline["f1"],
                           "delta_fp": proposed["fp"] - baseline["fp"],
                           "delta_fn": proposed["fn"] - baseline["fn"],
                           "mcnemar": mcnemar_exact(labels, incumbent_predictions, candidate_predictions),
                           "hierarchical_bootstrap_f1": hierarchical_bootstrap_delta(
                               labels, incumbent_predictions, candidate_predictions, groups,
                               samples=2000, seed=0,
                           )},
            "unavailable_arms": ["X1_HOLISTIC_STRONG", "X2_HOLISTIC_LOCAL",
                                  "X3_QUERY_CONDITIONED", "X4_VIGIL_LIKE", "X6_SLOW_PATH"]}


def run_model(rows) -> dict[str, Any]:
    del rows
    # Credential values are intentionally neither read nor serialised here.
    import os
    providers = {
        "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
        "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
        "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
        "local": ("GUARDIAN_LOCAL_API_KEY", os.environ.get("GUARDIAN_LOCAL_BASE_URL", "http://127.0.0.1:8000/v1")),
    }
    return {"providers": {name: {"credential_env": env, "credential_present": bool(os.environ.get(env)),
                                  "base_url": url, "live_probe": "not_requested"}
                          for name, (env, url) in providers.items()}}


def run_external(rows) -> dict[str, Any]:
    del rows
    return {"status": "not_run", "reason": "external adapters must be frozen before first labelled run"}


def run_final(rows) -> dict[str, Any]:
    del rows
    root = Path("outputs/next")
    files = {}
    for name in DEFAULT_OUTPUTS.values():
        path = root / name
        if path.exists() and name != "final_manifest.json":
            files[name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    return {"artifacts": files, "winner": None,
            "decision": "insufficient_evidence_until_frozen_internal_and_external_evaluations"}


RUNNERS = {"baseline": run_baseline, "policy": run_policy, "model": run_model,
           "tool": run_tool, "claims": run_claims, "internal": run_internal,
           "external": run_external, "final": run_final}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guardian Next evaluation entrypoint")
    parser.add_argument("stage", choices=tuple(RUNNERS))
    parser.add_argument("--input", type=Path, default=Path("valid.parquet"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    rows = _load(args.input) if args.stage not in {"model", "external", "final"} else []
    report = {"metadata": _metadata(args.input, args.stage), **RUNNERS[args.stage](rows)}
    output = args.output or Path("outputs/next") / DEFAULT_OUTPUTS[args.stage]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"stage": args.stage, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

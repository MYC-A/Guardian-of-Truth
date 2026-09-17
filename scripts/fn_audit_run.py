"""FN-audit canonical runner (directive §4-§8). DIAGNOSTIC ONLY.

Builds ONE canonical experimental line from HEAD:
1. freezes the exact canonical configuration (imported from the very functions
   that produced the final S3 run — no hand-copied values);
2. freezes ONE frontend cache (byte copy of the R1 mistral cache);
3. executes the full 46-case replay twice (RUN A, RUN B) with per-run working
   copies of the cache and hit/miss receipts;
4. verifies predictions/statuses/certificate digests are byte-identical and
   that ZERO live LLM calls occurred (cache misses = 0);
5. extracts the exact FN list (gold=1, prediction=0) — no manual selection.

No production code is modified. Tracing is added AROUND the frozen pipeline.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from real_valid_common import OUT_DIR, PROVIDERS, REPO_ROOT as _RR  # noqa: E402
from real_valid_adapter import competition_case, parse_tool_catalog  # noqa: E402

AUDIT_DIR = REPO_ROOT / "outputs" / "vnext" / "fn_audit"
SOURCE_CACHE = OUT_DIR / "R1" / "R1_llm_cache_mistral.json"
FROZEN_CACHE = AUDIT_DIR / "frontend_cache_frozen.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_canonical_config() -> dict:
    """§4: exact configuration, extracted from the live objects themselves."""
    from real_valid_run import guardian_for_mode
    from real_valid_common import (MISTRAL_BASE_URL, MISTRAL_MODEL,
                                   MISTRAL_MAX_OUTPUT_TOKENS, MISTRAL_TIMEOUT_SECONDS,
                                   MISTRAL_MAX_RETRIES, MISTRAL_INTERVAL_SECONDS,
                                   OUTER_TRANSPORT_RETRIES, OUTER_RETRY_DELAY_SECONDS)
    from guardian_truth.vnext.adapters import AdapterMode
    from dataclasses import asdict, replace
    from guardian_truth.vnext.e2e.e2e_types_v1 import SEMANTICS_ARMS

    # Build a throwaway backend-free guardian just to read its exact config.
    class _Null:
        def propose(self, *a, **k):
            raise AssertionError("config probe must never propose")

    guardian = guardian_for_mode(_Null(), "R1", schemas={"__probe__": {"name": "__probe__"}})
    semantics = replace(SEMANTICS_ARMS["B3"], must_act_abstention=True)
    config = {
        "head_at_freeze": _git_head(),
        "branch": _git_branch(),
        "architecture": "B4h-sound-v2 frozen @ 315bee335a467476732b47e1e7f412097222cd3b "
                        "(branch competition-real-valid-codex, candidate on top)",
        "arm_id": guardian.arm.arm_id,
        "policy_frontends": list(guardian.arm.policy_frontends),
        "goal_frontends": list(guardian.arm.goal_frontends),
        "adapter_mode": guardian.adapter_mode.name if hasattr(guardian.adapter_mode, "name")
                        else str(guardian.adapter_mode),
        "adapter_mode_value": AdapterMode.COMPETITION.name,
        "enable_t2": guardian.enable_t2,
        "max_worlds": guardian.max_worlds,
        "catalog_conformance": guardian.catalog_conformance,
        "goal_format_repair": guardian.goal_format_repair,
        "semantics": {
            "arm": "B3 (SEMANTICS_ARMS['B3']) + must_act_abstention=True (REP-08)",
            "flags": {k: v for k, v in asdict(semantics).items()},
        },
        "provider": {
            "name": "mistral",
            "base_url": MISTRAL_BASE_URL,
            "model": MISTRAL_MODEL,
            "max_output_tokens": MISTRAL_MAX_OUTPUT_TOKENS,
            "timeout_seconds": MISTRAL_TIMEOUT_SECONDS,
            "max_retries": MISTRAL_MAX_RETRIES,
            "response_format_mode": "none",
            "reasoning_effort": "dropped (provider compat shim)",
            "interval_seconds": MISTRAL_INTERVAL_SECONDS,
            "outer_transport_retries": OUTER_TRANSPORT_RETRIES,
            "outer_retry_delay_seconds": OUTER_RETRY_DELAY_SECONDS,
        },
        "input_adapter": {
            "module": "scripts/real_valid_adapter.py",
            "history_complete": True,
            "completeness_basis": "official task contract (prompt = full agent-visible context)",
            "t1_contracts": "absent (unknown)",
            "state_contract": "absent (unknown)",
            "authoritative_rows": "absent (unknown)",
        },
        "binary_adapter": "PROVED_ERROR->1, PROVED_NO_ERROR->0, INCONSISTENT->1, "
                           "UNRESOLVED/EXECUTION_ERROR->0 (frozen product adapter, COMPETITION mode)",
        "dataset": {
            "path": "valid.parquet",
            "case_count": 46,
            "note": "VIEWED DEVELOPMENT DATA",
        },
        "cache": {
            "source": str(SOURCE_CACHE.relative_to(REPO_ROOT)),
            "frozen_copy": str(FROZEN_CACHE.relative_to(REPO_ROOT)),
            "addressing": "sha256(task, payload, schema)",
        },
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (AUDIT_DIR / "canonical_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    return config


def _git_head() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=120).stdout.strip()


def _git_branch() -> str:
    import subprocess
    return subprocess.run(["git", "branch", "--show-current"], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def freeze_cache() -> dict:
    """§5: freeze ONE frontend cache; verify it is the one S3 wrote through."""
    if not FROZEN_CACHE.exists():
        shutil.copyfile(SOURCE_CACHE, FROZEN_CACHE)
    frozen_sha = sha256_file(FROZEN_CACHE)
    source_sha = sha256_file(SOURCE_CACHE)
    cache = json.loads(FROZEN_CACHE.read_text(encoding="utf-8"))
    manifest = {
        "model": PROVIDERS["mistral"]["model"],
        "provider": "mistral",
        "config_snapshot": "outputs/vnext/fn_audit/canonical_config.json",
        "entry_count": len(cache),
        "source_cache": str(SOURCE_CACHE.relative_to(REPO_ROOT)),
        "source_sha256": source_sha,
        "frozen_copy": str(FROZEN_CACHE.relative_to(REPO_ROOT)),
        "frozen_sha256": frozen_sha,
        "byte_identical_to_source": frozen_sha == source_sha,
        "creation_mode": "frozen byte copy of the cache the final S3 run wrote through "
                         "(last write 2026-09-17T00:22Z, same minute as the R1_final seal)",
        "replay_mode": "per-run working copies; hit/miss receipts recorded; "
                       "a non-zero miss count is a reproducibility failure",
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "transport_status_counts": _value_counts(cache, "transport_status"),
        "schema_status_counts": _value_counts(cache, "schema_status"),
    }
    (AUDIT_DIR / "cache_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def _value_counts(cache: dict, field: str) -> dict:
    counts = {}
    for record in cache.values():
        value = str(record.get(field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def run_once(label: str) -> dict:
    """One full 46-case replay with its own working cache copy."""
    from real_valid_common import build_backend
    from real_valid_run import guardian_for_mode

    run_dir = AUDIT_DIR / label
    run_dir.mkdir(parents=True, exist_ok=True)
    work_cache = run_dir / "llm_cache.json"
    shutil.copyfile(FROZEN_CACHE, work_cache)
    before_sha = sha256_file(work_cache)

    rows = _firewalled_rows()
    backend = build_backend(work_cache, provider="mistral")

    progress_path = run_dir / "progress.json"
    out = []
    for firewalled in rows:
        case_id = firewalled["id"]
        case = competition_case(firewalled)
        _, schemas_list = parse_tool_catalog(firewalled["prompt"])
        case_schemas = {schema["name"]: schema for schema in schemas_list}
        guardian = guardian_for_mode(backend, "R1", schemas=case_schemas,
                                     catalog_conformance=True)
        started = time.time()
        try:
            analysis = guardian.analyze_e2e_v1(case)
            cert = analysis.result.certificate
            record = {
                "case_id": case_id,
                "core_status": analysis.result.status.value,
                "binary": analysis.product_decision.binary_label,
                "used_fallback": analysis.product_decision.used_fallback,
                "certificate_valid": bool(analysis.result.certificate_check.valid)
                if analysis.result.certificate_check else None,
                "certificate_digests": {
                    "source_sha256": cert.source_sha256,
                    "ledger_sha256": cert.ledger_sha256,
                    "registry_sha256": cert.registry_sha256,
                    "problem_sha256": cert.problem_sha256,
                } if cert else None,
                "worlds": analysis.world_count,
                "required_worlds": analysis.required_worlds,
                "policy_reading_count": len(analysis.policy_readings),
                "goal_contract_count": len(analysis.goal_contracts),
                "frontend_failures": [{"component": c, "kind": k} for c, k, _ in analysis.frontend_statuses],
                "component_summary": dict(analysis.component_summary),
                "diagnostics": {
                    "primary": analysis.result.diagnostics.primary_reason.value
                    if analysis.result.diagnostics.primary_reason else None,
                    "contributing": [r.value for r in analysis.result.diagnostics.contributing_reasons],
                },
            }
        except Exception as failure:  # noqa: BLE001
            record = {"case_id": case_id, "core_status": "EXECUTION_ERROR",
                      "binary": 0, "error": f"{type(failure).__name__}:{str(failure)[:300]}"}
        out.append(record)
        progress_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{label}] {case_id}: {record['core_status']} binary={record['binary']} "
              f"({time.time()-started:.1f}s)", flush=True)

    after_sha = sha256_file(work_cache)
    receipts = backend.receipts
    misses = [r for r in receipts if not r["cache_hit"]]
    predictions_path = run_dir / f"{label.replace('_', '_')}_predictions.csv"
    with open(predictions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "label"])
        for row in sorted(out, key=lambda item: item["case_id"]):
            writer.writerow([row["case_id"], row["binary"] if row["binary"] is not None else 0])
    summary = {
        "label": label,
        "head": _git_head(),
        "case_count": len(out),
        "cache_entries_before": len(json.loads(work_cache.read_text(encoding="utf-8"))),
        "cache_sha_before": before_sha,
        "cache_sha_after": after_sha,
        "cache_mutated": before_sha != after_sha,
        "receipts_total": len(receipts),
        "receipts_misses": len(misses),
        "live_llm_calls": len(misses),
        "predictions_csv": str(predictions_path.relative_to(REPO_ROOT)),
        "predictions_sha256": sha256_file(predictions_path),
        "statuses": {row["case_id"]: row["core_status"] for row in out},
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def _firewalled_rows():
    from real_valid_common import load_firewalled_rows
    return load_firewalled_rows()


def compare_runs(a: dict, b: dict) -> dict:
    """§6 acceptance: byte-for-byte predictions, equal statuses, equal digests."""
    rows_a = {r["case_id"]: r for r in json.loads((AUDIT_DIR / "run_a" / "progress.json").read_text())}
    rows_b = {r["case_id"]: r for r in json.loads((AUDIT_DIR / "run_b" / "progress.json").read_text())}
    csv_a = (AUDIT_DIR / "run_a" / "run_a_predictions.csv").read_bytes()
    csv_b = (AUDIT_DIR / "run_b" / "run_b_predictions.csv").read_bytes()
    status_diff = {cid: (rows_a[cid]["core_status"], rows_b[cid]["core_status"])
                   for cid in rows_a if rows_a[cid]["core_status"] != rows_b[cid]["core_status"]}
    digest_diff = {}
    for cid in rows_a:
        da, db = rows_a[cid].get("certificate_digests"), rows_b[cid].get("certificate_digests")
        if da != db:
            digest_diff[cid] = {"A": da, "B": db}
    result = {
        "predictions_byte_identical": csv_a == csv_b,
        "predictions_sha256_run_a": hashlib.sha256(csv_a).hexdigest(),
        "predictions_sha256_run_b": hashlib.sha256(csv_b).hexdigest(),
        "statuses_identical": not status_diff,
        "status_diffs": status_diff,
        "certificate_digests_identical": not digest_diff,
        "certificate_digest_diffs": digest_diff,
        "live_llm_calls_run_a": a["live_llm_calls"],
        "live_llm_calls_run_b": b["live_llm_calls"],
        "cache_mutated_run_a": a["cache_mutated"],
        "cache_mutated_run_b": b["cache_mutated"],
        "accepted": (csv_a == csv_b and not status_diff and not digest_diff
                     and a["live_llm_calls"] == 0 and b["live_llm_calls"] == 0
                     and not a["cache_mutated"] and not b["cache_mutated"]),
    }
    (AUDIT_DIR / "reproducibility_gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def extract_fn_list() -> dict:
    """§8: exact FN list from the canonical run (gold joined post-hoc)."""
    import pandas as pd
    frame = pd.read_parquet(REPO_ROOT / "valid.parquet")
    gold = {str(r["id"]): int(r["label"]) for _, r in frame.iterrows()}
    rows = json.loads((AUDIT_DIR / "run_a" / "progress.json").read_text())
    fn = sorted([r for r in rows if gold[r["case_id"]] == 1 and r["binary"] == 0],
                key=lambda r: r["case_id"])
    tp = sorted([r["case_id"] for r in rows if gold[r["case_id"]] == 1 and r["binary"] == 1])
    fp = sorted([r["case_id"] for r in rows if gold[r["case_id"]] == 0 and r["binary"] == 1])
    tn = sorted([r["case_id"] for r in rows if gold[r["case_id"]] == 0 and r["binary"] == 0])
    confusion = {
        "TP": len(tp), "FP": len(fp), "FN": len(fn), "TN": len(tn),
        "precision": round(len(tp) / max(len(tp) + len(fp), 1), 4),
        "recall": round(len(tp) / max(len(tp) + len(fn), 1), 4),
        "f1": round(2 * len(tp) / max(2 * len(tp) + len(fp) + len(fn), 1), 4),
    }
    payload = {
        "source_run": "outputs/vnext/fn_audit/run_a/progress.json",
        "selection_rule": "gold==1 AND prediction==0 (machine selection, no manual curation)",
        "expected_fn_count": 15,
        "confusion": confusion,
        "tp_ids": tp, "fp_ids": fp, "tn_ids": tn,
        "fn": [{"case_id": r["case_id"], "core_status": r["core_status"],
                "primary": (r.get("diagnostics") or {}).get("primary"),
                "frontend_failures": r.get("frontend_failures", []),
                "component_summary": r.get("component_summary", {})} for r in fn],
    }
    (AUDIT_DIR / "fn_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="all",
                        choices=("config", "cache", "run-a", "run-b", "compare", "fn-list", "all"))
    args = parser.parse_args()
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    if args.stage in ("config", "all"):
        config = freeze_canonical_config()
        print("canonical config frozen; head =", config["head_at_freeze"])
    if args.stage in ("cache", "all"):
        manifest = freeze_cache()
        print("cache frozen:", manifest["entry_count"], "entries; byte-identical:",
              manifest["byte_identical_to_source"])
    if args.stage in ("run-a", "all"):
        summary = run_once("run_a")
        print(json.dumps({k: summary[k] for k in
                          ("case_count", "live_llm_calls", "cache_mutated", "predictions_sha256")}))
    if args.stage in ("run-b", "all"):
        summary = run_once("run_b")
        print(json.dumps({k: summary[k] for k in
                          ("case_count", "live_llm_calls", "cache_mutated", "predictions_sha256")}))
    if args.stage in ("compare", "all"):
        a = json.loads((AUDIT_DIR / "run_a" / "run_summary.json").read_text())
        b = json.loads((AUDIT_DIR / "run_b" / "run_summary.json").read_text())
        result = compare_runs(a, b)
        print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.stage in ("fn-list", "all"):
        payload = extract_fn_list()
        print(json.dumps(payload["confusion"], ensure_ascii=False))
        print("FN count:", len(payload["fn"]))


if __name__ == "__main__":
    main()

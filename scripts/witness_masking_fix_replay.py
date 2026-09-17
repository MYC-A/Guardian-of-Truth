"""Witness-masking fix verification replay (post-fix, diagnostic + acceptance).

Re-runs the frozen 46 real-valid cases with EXACTLY the canonical audit
configuration and the frozen frontend cache (a working copy; the frozen copy
is never mutated), then verifies the fix directive's acceptance conditions:

1. telecom t7 (the masked-witness FN) flips UNRESOLVED -> PROVED_ERROR with
   a VALID certificate;
2. NO other case changes its prediction (byte-identical predictions except
   t7), no new false-certified verdicts (FP stays 0);
3. zero live LLM calls (cache misses = 0), cache not mutated;
4. confusion: TP=9 FP=0 FN=14 TN=23.

Output: outputs/vnext/witness_masking_fix/
"""
from __future__ import annotations

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

from real_valid_common import OUT_DIR  # noqa: E402
from real_valid_adapter import competition_case, parse_tool_catalog  # noqa: E402

AUDIT_DIR = REPO_ROOT / "outputs" / "vnext" / "fn_audit"
FROZEN_CACHE = AUDIT_DIR / "frontend_cache_frozen.json"
FIX_DIR = REPO_ROOT / "outputs" / "vnext" / "witness_masking_fix"
BASELINE_RUN_A = AUDIT_DIR / "run_a"

TELECOM_T7 = ("telecom__mms_issueairplane_mode_on-bad_network_preference-"
              "bad_wifi_calling-data_usage_exce::t7")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from real_valid_common import build_backend, load_firewalled_rows
    from real_valid_run import guardian_for_mode

    FIX_DIR.mkdir(parents=True, exist_ok=True)
    work_cache = FIX_DIR / "llm_cache.json"
    shutil.copyfile(FROZEN_CACHE, work_cache)
    before_sha = sha256_file(work_cache)

    rows = load_firewalled_rows()
    backend = build_backend(work_cache, provider="mistral")

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
                "world_error_values": [proof.error_value.name
                                       for proof in analysis.result.world_proofs],
                "false_witnesses_per_world": [
                    [oid for oid, value in proof.obligation_safety if value.name == "FALSE"]
                    for proof in analysis.result.world_proofs],
                "frontend_failures": [{"component": c, "kind": k}
                                      for c, k, _ in analysis.frontend_statuses],
                "diagnostics": {
                    "primary": analysis.result.diagnostics.primary_reason.value
                    if analysis.result.diagnostics.primary_reason else None,
                    "contributing": [r.value for r in
                                    analysis.result.diagnostics.contributing_reasons],
                },
            }
        except Exception as failure:  # noqa: BLE001
            record = {"case_id": case_id, "core_status": "EXECUTION_ERROR",
                      "binary": 0, "error": f"{type(failure).__name__}:{str(failure)[:300]}"}
        out.append(record)
        print(f"[fix-replay] {case_id}: {record['core_status']} binary={record['binary']} "
              f"({time.time()-started:.1f}s)", flush=True)

    receipts = backend.receipts
    misses = [r for r in receipts if not r["cache_hit"]]
    after_sha = sha256_file(work_cache)

    predictions_path = FIX_DIR / "fix_predictions.csv"
    with open(predictions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "label"])
        for row in sorted(out, key=lambda item: item["case_id"]):
            writer.writerow([row["case_id"], row["binary"] if row["binary"] is not None else 0])

    # ---- comparison against the sealed audit RUN A ------------------------
    baseline_rows = {r["case_id"]: r for r in
                     json.loads((BASELINE_RUN_A / "progress.json").read_text())}
    baseline_csv = (BASELINE_RUN_A / "run_a_predictions.csv").read_bytes()
    status_diffs = {cid: (baseline_rows[cid]["core_status"], r["core_status"])
                    for r in out if (cid := r["case_id"]) in baseline_rows
                    and baseline_rows[cid]["core_status"] != r["core_status"]}
    binary_diffs = {cid: (baseline_rows[cid]["binary"], r["binary"])
                    for r in out if (cid := r["case_id"]) in baseline_rows
                    and baseline_rows[cid]["binary"] != r["binary"]}
    cert_flips = {r["case_id"]: {"before": baseline_rows[r["case_id"]].get("certificate_valid"),
                                 "after": r.get("certificate_valid")}
                  for r in out
                  if r["case_id"] in baseline_rows
                  and baseline_rows[r["case_id"]].get("certificate_valid") != r.get("certificate_valid")}

    # ---- gold join (scoring only; inference never saw labels) -------------
    import pandas as pd
    frame = pd.read_parquet(REPO_ROOT / "valid.parquet")
    gold = {str(r["id"]): int(r["label"]) for _, r in frame.iterrows()}
    tp = sorted(r["case_id"] for r in out if gold[r["case_id"]] == 1 and r["binary"] == 1)
    fp = sorted(r["case_id"] for r in out if gold[r["case_id"]] == 0 and r["binary"] == 1)
    fn = sorted(r["case_id"] for r in out if gold[r["case_id"]] == 1 and r["binary"] == 0)
    tn = sorted(r["case_id"] for r in out if gold[r["case_id"]] == 0 and r["binary"] == 0)
    confusion = {
        "TP": len(tp), "FP": len(fp), "FN": len(fn), "TN": len(tn),
        "precision": round(len(tp) / max(len(tp) + len(fp), 1), 4),
        "recall": round(len(tp) / max(len(tp) + len(fn), 1), 4),
        "f1": round(2 * len(tp) / max(2 * len(tp) + len(fp) + len(fn), 1), 4),
    }

    t7 = next(r for r in out if r["case_id"] == TELECOM_T7)
    false_certified = [r["case_id"] for r in out
                       if r["binary"] == 1 and gold[r["case_id"]] == 0]

    summary = {
        "head": _git_head(),
        "case_count": len(out),
        "live_llm_calls": len(misses),
        "cache_mutated": before_sha != after_sha,
        "cache_sha_before": before_sha,
        "cache_sha_after": after_sha,
        "baseline": "outputs/vnext/fn_audit/run_a (sealed audit replay of HEAD f126c00)",
        "status_diffs_vs_run_a": status_diffs,
        "binary_diffs_vs_run_a": binary_diffs,
        "certificate_validity_flips": cert_flips,
        "confusion": confusion,
        "tp_ids": tp, "fp_ids": fp, "fn_ids": fn, "tn_ids": tn,
        "t7_record": t7,
        "acceptance": {
            "t7_unresolved_to_proved_error": t7["core_status"] == "PROVED_ERROR",
            "t7_certificate_valid": t7.get("certificate_valid") is True,
            "no_new_false_certified": not false_certified,
            "only_t7_changed": set(binary_diffs) == {TELECOM_T7},
            "zero_live_calls": len(misses) == 0,
            "cache_unchanged": before_sha == after_sha,
            "expected_confusion": confusion == {"TP": 9, "FP": 0, "FN": 14, "TN": 23,
                                                "precision": 1.0, "recall": 0.3913,
                                                "f1": 0.5625},
        },
    }
    summary["accepted"] = all(summary["acceptance"].values())
    (FIX_DIR / "fix_replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (FIX_DIR / "progress.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({"confusion": confusion, "status_diffs": status_diffs,
                      "binary_diffs": binary_diffs,
                      "acceptance": summary["acceptance"],
                      "accepted": summary["accepted"]}, indent=1))
    return 0 if summary["accepted"] else 1


def _git_head() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=120).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pre-benchmark soundness audit regression runner (directive sections 41-42).

Runs, on the VIEWED DEVELOPMENT corpora (dev32 + holdout112, regression
diagnostics ONLY - never a fresh benchmark):
  1. B0  byte-fidelity replay gate (offline, frozen corpus caches): the B0 arm
     must reproduce the frozen E2E V1 (E0) predictions EXACTLY. All soundness
     fixes are gated behind conservative_state/alternative_groups semantics
     flags that B0 leaves off, so fidelity must hold by construction.
  2. B4h soundness-fixed replay: the B4h arm with the B4h-sound-v1 semantics,
     replayed OFFLINE against the merged per-slice live caches persisted by
     the cycle-3 foreground runner (zero new LLM calls; every fix is
     LLM-payload-neutral).

Reports old-vs-new metrics per corpus for the audit document.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend, build_live_backend  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS  # noqa: E402
from guardian_truth.vnext.e2e.experiment_v1 import load_corpus, registry_for  # noqa: E402

CORPORA = {
    "dev": ("outputs/vnext/e2e_v1_dev_corpus.json",
            "outputs/vnext/e2e_v1_dev_gold.json",
            "outputs/vnext/e2e_v1_dev_llm_cache.json"),
    "holdout": ("outputs/vnext/e2e_v1_holdout_corpus.json",
                "outputs/vnext/e2e_v1_holdout_gold.json",
                "outputs/vnext/e2e_v1_holdout_llm_cache.json"),
}
SLICES = 6


class OfflineInner:
    def __init__(self):
        self.misses = []

    def propose(self, task, payload, schema):
        self.misses.append((task, json.dumps(payload, sort_keys=True)[:200]))
        raise RuntimeError(f"OFFLINE CACHE MISS: task={task}")


def merged_live_cache(corpus_name: str, arm: str) -> Path:
    """Merge the persisted per-slice live caches into one replay cache."""
    merged = {}
    for i in range(SLICES):
        path = ROOT / f"outputs/vnext/e2e_v1_cycle3_{corpus_name}_{arm}_live_cache_slice{i}.json"
        if path.exists():
            merged.update(json.loads(path.read_text(encoding="utf-8")))
    out = ROOT / f"outputs/vnext/soundness_audit_{corpus_name}_{arm}_replay_cache.json"
    out.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return out


def run_arm(arm_name, frontends, semantics_key, corpus_name, cases, backend):
    arm = E2EArmConfig(arm_name, frontends, ("conservative",))
    semantics = SEMANTICS_ARMS[semantics_key]
    rows = []
    inner = OfflineInner()
    for case in cases:
        guardian = GuardianE2EV1(backend, registry=registry_for(case), arm=arm,
                                  max_worlds=4096, adapter_mode=AdapterMode.AUDIT,
                                  semantics=semantics)
        try:
            analysis = guardian.analyze_e2e_v1(case)
            rows.append({"case_id": case.case_id, "family": case.family,
                         "core_status": analysis.result.status.value,
                         "certificate_valid": bool(analysis.result.certificate_check
                                                   and analysis.result.certificate_check.valid)
                         if analysis.result.certificate_check else None})
        except Exception as error:
            rows.append({"case_id": case.case_id, "family": case.family,
                         "core_status": "UNRESOLVED", "certificate_valid": False,
                         "error": f"{type(error).__name__}:{str(error)[:200]}"})
    return rows, inner.misses


def score(rows, gold):
    gold_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_ERROR"}
    gold_no_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_NO_ERROR"}
    tp = [r for r in rows if r["case_id"] in gold_error and r["core_status"] == "PROVED_ERROR"]
    fp = [r for r in rows if r["case_id"] not in gold_error and r["core_status"] == "PROVED_ERROR"]
    fn = [r for r in rows if r["case_id"] in gold_error and r["core_status"] != "PROVED_ERROR"]
    tn = [r for r in rows if r["case_id"] in gold_no_error and r["core_status"] == "PROVED_NO_ERROR"]
    fpne = [r for r in rows if r["case_id"] not in gold_no_error and r["core_status"] == "PROVED_NO_ERROR"]
    precision = len(tp) / (len(tp) + len(fp)) if tp or fp else None
    recall = len(tp) / len(gold_error) if gold_error else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    status_counts = {}
    for row in rows:
        status_counts[row["core_status"]] = status_counts.get(row["core_status"], 0) + 1
    uncertified = [r for r in rows if r["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}
                   and not r.get("certificate_valid")]
    return {"total": len(rows), "TP": len(tp), "FP": len(fp), "FN": len(fn), "TN": len(tn),
            "false_certified_error": len(fp), "false_certified_no_error": len(fpne),
            "error_precision": round(precision, 4) if precision is not None else None,
            "error_recall": round(recall, 4) if recall is not None else None,
            "error_f1": round(f1, 4) if f1 is not None else None,
            "uncertified_definitive": len(uncertified),
            "status_counts": status_counts,
            "fp_case_ids": [r["case_id"] for r in fp],
            "fpne_case_ids": [r["case_id"] for r in fpne],
            "fn_case_ids": [r["case_id"] for r in fn],
            "changed_to_unresolved": [r["case_id"] for r in rows
                                      if r["core_status"] == "UNRESOLVED"
                                      and gold.get(r["case_id"], {}).get("core_status")
                                      in {"PROVED_ERROR", "PROVED_NO_ERROR"}][:40]}


def main():
    report = {"version": "pre_benchmark_soundness_regression",
              "viewed_development_data_only": True,
              "corpora": {}}
    for corpus_name in ("dev", "holdout"):
        corpus_path, gold_path, cache_path = CORPORA[corpus_name]
        cases = load_corpus(ROOT / corpus_path)
        gold = json.loads((ROOT / gold_path).read_text(encoding="utf-8"))
        entry = {}

        # ---- B0 fidelity (offline frozen cache) ----
        backend_b0 = E2ECachingBackend(OfflineInner(), cache_path=ROOT / cache_path)
        rows_b0, _ = run_arm("B0", ("h0",), "B0", corpus_name, cases, backend_b0)
        frozen = json.loads((ROOT / f"outputs/vnext/e2e_v1_cycle3_{corpus_name}_B0_predictions.json")
                            .read_text(encoding="utf-8"))
        frozen_map = {row["case_id"]: row["core_status"] for row in frozen}
        divergences = [row["case_id"] for row in rows_b0
                       if frozen_map.get(row["case_id"]) != row["core_status"]]
        entry["B0_fidelity"] = {"cases": len(rows_b0), "divergences": divergences,
                                "byte_faithful": not divergences}

        # ---- B4h soundness-fixed replay (merged live caches, zero new calls) ----
        merged = merged_live_cache(corpus_name, "B4h")
        corpus_cache = ROOT / cache_path
        backend_b4h = build_live_backend(cache_path=None, env_path=ROOT / ".env")
        if merged.exists():
            backend_b4h.cache.update(json.loads(merged.read_text(encoding="utf-8")))
        if corpus_cache.exists():
            backend_b4h.cache.update(json.loads(corpus_cache.read_text(encoding="utf-8")))
        backend_b4h.cache_path = None  # replay-only: never write
        rows_b4h, misses = run_arm("B4h", ("h0_hist",), "B3", corpus_name, cases, backend_b4h)
        entry["B4h_soundness_fixed"] = score(rows_b4h, gold)
        entry["B4h_soundness_fixed"]["cache_misses"] = len(misses)
        if misses:
            entry["B4h_soundness_fixed"]["cache_miss_detail"] = misses[:5]

        # old frozen B4h predictions for comparison
        old = []
        for i in range(SLICES):
            p = ROOT / f"outputs/vnext/e2e_v1_cycle3_{corpus_name}_B4h_predictions_slice{i}.json"
            if p.exists():
                old.extend(json.loads(p.read_text(encoding="utf-8")))
        if old:
            old_map = {row["case_id"]: row["core_status"] for row in old}
            changed = [{"case_id": row["case_id"], "old": old_map.get(row["case_id"]),
                        "new": row["core_status"]}
                       for row in rows_b4h if old_map.get(row["case_id"]) != row["core_status"]]
            entry["B4h_verdict_changes"] = changed
        report["corpora"][corpus_name] = entry

    out = ROOT / "outputs/vnext/pre_benchmark_soundness_regression.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({c: {"B0_byte_faithful": e["B0_fidelity"]["byte_faithful"],
                          "B4h_new": {k: e["B4h_soundness_fixed"][k]
                                      for k in ("TP", "FP", "FN", "TN",
                                                "false_certified_error",
                                                "false_certified_no_error",
                                                "error_precision", "error_recall",
                                                "error_f1", "cache_misses",
                                                "status_counts")},
                          "verdict_changes": len(e.get("B4h_verdict_changes", []))}
                       for c, e in report["corpora"].items()}, indent=1))


if __name__ == "__main__":
    main()

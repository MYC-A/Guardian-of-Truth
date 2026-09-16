"""Cycle-3 causal ablation runner (directive sections 10-13): B0/B1/B2/B3/B4
on DEVELOPMENT data only (the 32-case dev corpus + the 112-case holdout which
is now VIEWED DEVELOPMENT DATA - never a fresh headline holdout).

Arms (one change per step, never bundled):
  B0  frozen E2E V1 semantics (byte-faithful replay gate; must reproduce the
      frozen E0 predictions exactly - verified by scripts/check_b0_full_replay.py)
  B1  B0 + conservative temporal/BOTH state semantics
  B2  B1 + alternative-actions fix (disjunctive satisfaction groups)
  B3  B2 + INCONSISTENT status surfacing + claim-typing guards
  B4h B3 + exact historical H0 frontend (frozen Agent-1 policy line)
  B4g B3 + exact historical GRS frontend (frozen Agent-1 policy line)

B0-B3 run fully offline against the persisted per-corpus LLM caches (zero
live calls). B4h/B4g need live calls ONLY for the frozen historical policy
tasks and the re-bound operational bindings; every other proposal replays
from the persisted corpus caches. All live calls are persisted to a fresh
content-addressed cache file so the run is exactly reproducible.

Metrics per arm: TP/FP/FN/TN, ERROR precision/recall/F1,
correct-definitive coverage, UNRESOLVED rate, false-certified ERROR,
false-certified NO_ERROR, INCONSISTENT rate, certificate validity.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend, build_live_backend  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS  # noqa: E402
from guardian_truth.vnext.e2e.experiment_v1 import load_corpus, registry_for  # noqa: E402
from guardian_truth.vnext.e2e.policy_historical_v1 import HISTORICAL_PROVENANCE  # noqa: E402

CORPORA = {
    "dev": ("outputs/vnext/e2e_v1_dev_corpus.json",
            "outputs/vnext/e2e_v1_dev_gold.json",
            "outputs/vnext/e2e_v1_dev_llm_cache.json"),
    "holdout": ("outputs/vnext/e2e_v1_holdout_corpus.json",
                "outputs/vnext/e2e_v1_holdout_gold.json",
                "outputs/vnext/e2e_v1_holdout_llm_cache.json"),
}

ARMS = {
    "B0": (("h0",), "B0"),
    "B1": (("h0",), "B1"),
    "B2": (("h0",), "B2"),
    "B3": (("h0",), "B3"),
    "B4h": (("h0_hist",), "B3"),
    "B4g": (("grs_hist",), "B3"),
}
LIVE_ARMS = {"B4h", "B4g"}


class OfflineInner:
    def __init__(self):
        self.misses = 0

    def propose(self, task, payload, schema):
        self.misses += 1
        raise RuntimeError(f"OFFLINE CACHE MISS in frozen-cache arm: task={task}")


def make_backend(corpus_cache: Path, live: bool, live_cache: Path):
    if not live:
        return E2ECachingBackend(OfflineInner(), cache_path=corpus_cache)
    backend = build_live_backend(cache_path=None, env_path=ROOT / ".env")
    if live_cache.exists():
        backend.cache.update(json.loads(live_cache.read_text(encoding="utf-8")))
    if corpus_cache.exists():
        backend.cache.update(json.loads(corpus_cache.read_text(encoding="utf-8")))
    backend.cache_path = live_cache
    return backend


def run_arm(arm_name: str, corpus_name: str, cases, backend, progress_file: Path):
    frontends, semantics_key = ARMS[arm_name]
    arm = E2EArmConfig(arm_name, frontends, ("conservative",))
    semantics = SEMANTICS_ARMS[semantics_key]
    rows = []
    if progress_file.exists():
        rows = json.loads(progress_file.read_text(encoding="utf-8"))
    done = {row["case_id"] for row in rows}
    for case in cases:
        if case.case_id in done:
            continue
        guardian = GuardianE2EV1(backend, registry=registry_for(case), arm=arm,
                                  max_worlds=4096, adapter_mode=AdapterMode.AUDIT,
                                  semantics=semantics)
        started = time.time()
        try:
            analysis = guardian.analyze_e2e_v1(case)
            rows.append(_row(analysis, case, arm_name, time.time() - started))
        except Exception as error:  # a crashed case is UNRESOLVED, never a verdict
            rows.append({"case_id": case.case_id, "family": case.family, "arm": arm_name,
                         "core_status": "UNRESOLVED", "certificate_valid": False,
                         "worlds": 0, "required_worlds": 0, "frontend_failures": [],
                         "component_summary": {}, "elapsed_s": round(time.time() - started, 2),
                         "error": f"{type(error).__name__}:{str(error)[:200]}"})
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        progress_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def _row(analysis, case, arm_name, elapsed) -> dict:
    return {"case_id": case.case_id, "family": case.family, "arm": arm_name,
            "core_status": analysis.result.status.value,
            "certificate_valid": bool(analysis.result.certificate_check and analysis.result.certificate_check.valid)
            if analysis.result.certificate_check else None,
            "worlds": analysis.world_count, "required_worlds": analysis.required_worlds,
            "frontend_failures": [{"component": name, "kind": kind} for name, kind, _ in analysis.frontend_statuses],
            "policy_reading_count": len(analysis.policy_readings),
            "goal_contract_count": len(analysis.goal_contracts),
            "component_summary": dict(analysis.component_summary),
            "elapsed_s": round(elapsed, 2)}


def score(rows, gold) -> dict:
    total = len(rows)
    definitive = [r for r in rows if r["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}]
    gold_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_ERROR"}
    gold_no_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_NO_ERROR"}
    tp = [r for r in rows if r["case_id"] in gold_error and r["core_status"] == "PROVED_ERROR"]
    fp = [r for r in rows if r["case_id"] not in gold_error and r["core_status"] == "PROVED_ERROR"]
    fn = [r for r in rows if r["case_id"] in gold_error and r["core_status"] != "PROVED_ERROR"]
    tn = [r for r in rows if r["case_id"] in gold_no_error and r["core_status"] == "PROVED_NO_ERROR"]
    fp_no_error = [r for r in rows if r["case_id"] not in gold_no_error and r["core_status"] == "PROVED_NO_ERROR"]
    correct_definitive = [r for r in definitive
                          if r["core_status"] == gold.get(r["case_id"], {}).get("core_status")]
    uncertified = [r for r in definitive if not r.get("certificate_valid")]
    precision = len(tp) / (len(tp) + len(fp)) if tp or fp else None
    recall = len(tp) / len(gold_error) if gold_error else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    status_counts = {}
    for row in rows:
        status_counts[row["core_status"]] = status_counts.get(row["core_status"], 0) + 1
    return {
        "total": total,
        "TP": len(tp), "FP": len(fp), "FN": len(fn), "TN": len(tn),
        "FP_NO_ERROR": len(fp_no_error),
        "false_certified_error": len(fp), "false_certified_no_error": len(fp_no_error),
        "error_precision": round(precision, 4) if precision is not None else None,
        "error_recall": round(recall, 4) if recall is not None else None,
        "error_f1": round(f1, 4) if f1 is not None else None,
        "definitive_coverage": round(len(definitive) / total, 4) if total else 0,
        "correct_definitive_coverage": round(len(correct_definitive) / total, 4) if total else 0,
        "unresolved_rate": round(status_counts.get("UNRESOLVED", 0) / total, 4) if total else 0,
        "inconsistent_rate": round(status_counts.get("INCONSISTENT", 0) / total, 4) if total else 0,
        "uncertified_definitive": len(uncertified),
        "status_counts": status_counts,
        "fp_case_ids": [r["case_id"] for r in fp],
        "fn_case_ids": [r["case_id"] for r in fn],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", default="B0,B1,B2,B3,B4h,B4g")
    parser.add_argument("--corpora", default="dev,holdout")
    parser.add_argument("--prefix", default="e2e_v1_cycle3")
    parser.add_argument("--results", default="outputs/vnext/e2e_v1_cycle3_ablation.json")
    parser.add_argument("--slice", default=None,
                        help="i/N: run only the i-th of N equal slices (parallel live runs); "
                             "slice predictions land in *_slice{i} progress files")
    args = parser.parse_args()

    results_path = ROOT / args.results
    results = {"version": "guardian_e2e_cycle3_ablation",
               "development_data_only": True,
               "holdout_is_viewed_development_data": True,
               "historical_provenance": HISTORICAL_PROVENANCE,
               "arms": {}, "per_corpus": {}}
    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        results["historical_provenance"] = HISTORICAL_PROVENANCE

    for corpus_name in args.corpora.split(","):
        corpus_path, gold_path, cache_path = CORPORA[corpus_name]
        cases = load_corpus(ROOT / corpus_path)
        gold = json.loads((ROOT / gold_path).read_text(encoding="utf-8"))
        for arm_name in args.arms.split(","):
            live = arm_name in LIVE_ARMS
            suffix = "" if not args.slice else f"_slice{args.slice.split('/')[0]}"
            live_cache = ROOT / f"outputs/vnext/{args.prefix}_{corpus_name}_{arm_name}_live_cache{suffix}.json"
            progress = ROOT / f"outputs/vnext/{args.prefix}_{corpus_name}_{arm_name}_predictions{suffix}.json"
            selected = cases
            if args.slice:
                index, total = (int(part) for part in args.slice.split("/"))
                selected = [case for position, case in enumerate(cases) if position % total == index]
            backend = make_backend(ROOT / cache_path, live, live_cache)
            rows = run_arm(arm_name, corpus_name, selected, backend, progress)
            metrics = score(rows, gold)
            results["per_corpus"].setdefault(corpus_name, {})[arm_name] = metrics
            print(f"{corpus_name} {arm_name}: TP={metrics['TP']} FP={metrics['FP']} "
                  f"FN={metrics['FN']} TN={metrics['TN']} FPE={metrics['false_certified_error']} "
                  f"FPNE={metrics['false_certified_no_error']} "
                  f"P={metrics['error_precision']} R={metrics['error_recall']} F1={metrics['error_f1']} "
                  f"cov={metrics['correct_definitive_coverage']} unres={metrics['unresolved_rate']}")
            if live:
                backend.persist_receipts(ROOT / f"outputs/vnext/{args.prefix}_{corpus_name}_{arm_name}_receipts.json")

    # combined development-data metrics per arm
    for arm_name in args.arms.split(","):
        combined_rows, combined_gold = [], {}
        for corpus_name in args.corpora.split(","):
            corpus_path, gold_path, _ = CORPORA[corpus_name]
            gold = json.loads((ROOT / gold_path).read_text(encoding="utf-8"))
            combined_gold.update(gold)
            progress_dir = ROOT / "outputs/vnext"
            files = ([progress_dir / f"{args.prefix}_{corpus_name}_{arm_name}_predictions.json"] if
                     (progress_dir / f"{args.prefix}_{corpus_name}_{arm_name}_predictions.json").exists() else [])
            files += sorted(progress_dir.glob(f"{args.prefix}_{corpus_name}_{arm_name}_predictions_slice*.json"))
            seen_ids = set()
            for file in files:
                for row in json.loads(file.read_text(encoding="utf-8")):
                    if row["case_id"] not in seen_ids:
                        seen_ids.add(row["case_id"])
                        combined_rows.append(row)
        if combined_rows:
            results["arms"][arm_name] = score(combined_rows, combined_gold)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {results_path}")


if __name__ == "__main__":
    main()

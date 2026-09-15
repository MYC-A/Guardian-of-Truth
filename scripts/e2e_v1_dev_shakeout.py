"""E2E V1 live DEV shakeout (pre-freeze, spec Phase 6).

Runs the full per-case semantic pipeline live on a few DEV cases (slices of
the fresh corpus by cohort, mechanically inspected WITHOUT any gold join) to
shake out live-model integration issues BEFORE the architecture freeze.
Dev artifacts live in outputs/vnext/e2e_v1_dev/ and never enter the fresh run.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.settings import load_env_file
from guardian_truth.vnext.integrity import digest, write_new
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause

import evaluate_vnext_e2e_v1 as runner
from guardian_truth.vnext.e2e import fresh_corpus_v1
from guardian_truth.vnext.e2e.core_v1 import analyze_e2e_v1

DEV = ROOT / "outputs" / "vnext" / "e2e_v1_dev"
DEV.mkdir(parents=True, exist_ok=True)


def main() -> int:
    load_env_file(".env")
    cases = fresh_corpus_v1.build_fresh_corpus()
    # dev slice: one case per representative cohort family
    wanted = ["safe_flat_0", "err_flat_0", "condition_frozen", "exception_none",
              "false_success_0", "prerequisite_missing", "wrong_tool_read_vs_mutation"]
    selected = [item for item in cases if item.case_id in wanted]
    for item in selected:
        marker = DEV / f"{item.case_id}.json"
        if marker.exists():
            continue
        from guardian_truth.vnext.experiment import quota_pause_reason
        configuration = dict(runner.CONFIG, dev=True, case=item.case_id)
        delegate, live = runner._make_delegate(".env")
        backend = PersistedSemanticBackend(
            delegate, DEV / "requests", item.case_id,
            configuration_sha256=digest(configuration),
            live_records=live)
        try:
            semantic = runner.run_semantic_passes(item.sources, runner._deps(backend))
        except ProviderPause as pause:
            print(json.dumps({"status": "PROVIDER_PAUSE", "reason": str(pause)}))
            return 0
        record = {"case_id": item.case_id, "cohort": item.cohort,
                  "requests": len(backend.records),
                  "h0_status": semantic.h0_result.status,
                  "grs_status": semantic.grs_result.status,
                  "conservative_frames": len(semantic.conservative_contract.frames),
                  "rule_frames_frames": len(semantic.rule_frames_contract.frames),
                  "binding_failures": list(semantic.binding.failures)[:6],
                  "binding_unbound": list(semantic.binding.unbound_units)[:6],
                  "claim_failures": [[t, r.value] for t, r in semantic.claim_graph.failures]}
        # mechanical arm composition (no gold join)
        for arm in ("E0", "E4"):
            try:
                output = analyze_e2e_v1(item.sources, semantic, arm)
                record[arm] = {"status": output.result.status.value,
                               "cert": bool(output.result.certificate_check.valid)
                               if output.result.certificate_check else None,
                               "worlds": output.required_worlds}
            except Exception as error:  # noqa: BLE001
                record[arm] = {"status": "CRASH", "error": f"{type(error).__name__}: {error}"}
        write_new(marker, record)
        print(json.dumps(record), flush=True)
    print(json.dumps({"status": "DEV_SHAKEOUT_DONE", "cases": len(selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""BASELINE ATTEMPT (directive §10): run frozen B4h-sound-v2 on the 46 public
valid.parquet cases WITHOUT any fixes, record the exact blocker per case.

Attempt A (direct): E2ECaseInput built by naive stuffing — the whole raw
prompt into system_policy, the raw response into target_response, everything
else absent. This is the most direct "analyze(prompt, response)" call the
frozen pipeline admits; every failure observed here is a real dependency gap
of the frozen research pipeline, classified with the directive taxonomy:

  MISSING_COMPETITION_ADAPTER / MISSING_T1 / MISSING_STATE_CONTRACT /
  MISSING_AUTHORITATIVE_ROWS / MISSING_LLM_CACHE / INPUT_FORMAT_MISMATCH /
  FRONTEND_TRANSPORT_REQUIRED / RESEARCH_RUNNER_ONLY / EXECUTION_ERROR / OK
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from real_valid_common import (OUT_DIR, PROVIDERS, REPO_ROOT, b4h_sound_v2_guardian,
                               build_backend, load_firewalled_rows, load_progress, save_progress)

import sys

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput  # noqa: E402

BLOCKER_MAP = {
    "policy_h0_hist": "POLICY_FRONTEND",
    "goal_conservative": "GOAL_FRONTEND",
}


def classify_blockers(analysis_row: dict, case_input: E2ECaseInput) -> list[str]:
    blockers = []
    if not case_input.user_request.strip():
        blockers.append("INPUT_FORMAT_MISMATCH:goal_axis_absent(user_request empty in direct stuffing)")
    if not case_input.t1_contracts:
        blockers.append("MISSING_T1:no trusted tool contracts")
    if not case_input.state_contract:
        blockers.append("MISSING_STATE_CONTRACT:preservation lowering unavailable")
    if not case_input.history_complete:
        blockers.append("HISTORY_COMPLETE_UNKNOWN:absence proofs blocked")
    if not case_input.authoritative_policy_behaviors and not case_input.authoritative_goal_behaviors:
        blockers.append("MISSING_AUTHORITATIVE_ROWS:behavioral closure unavailable")
    for failure in analysis_row.get("frontend_failures", []):
        component = failure.get("component", "")
        kind = failure.get("kind", "")
        blockers.append(f"FRONTEND_{BLOCKER_MAP.get(component, component.upper())}_{kind}")
    if analysis_row.get("used_fallback"):
        blockers.append(f"NON_DEFINITIVE:{analysis_row.get('core_status')}")
    return blockers


def row_of(analysis, case_input, elapsed) -> dict:
    return {
        "case_id": analysis.case_id,
        "arm": analysis.arm_id,
        "core_status": analysis.result.status.value,
        "binary": analysis.product_decision.binary_label,
        "used_fallback": analysis.product_decision.used_fallback,
        "certificate_valid": bool(analysis.result.certificate_check and analysis.result.certificate_check.valid)
        if analysis.result.certificate_check else None,
        "worlds": analysis.world_count,
        "required_worlds": analysis.required_worlds,
        "frontend_failures": [{"component": c, "kind": k} for c, k, _ in analysis.frontend_statuses],
        "policy_reading_count": len(analysis.policy_readings),
        "goal_contract_count": len(analysis.goal_contracts),
        "component_summary": dict(analysis.component_summary),
        "diagnostics": {
            "primary": analysis.result.diagnostics.primary_reason.value
            if analysis.result.diagnostics.primary_reason else None,
            "contributing": [r.value for r in analysis.result.diagnostics.contributing_reasons],
            "missing_evidence": list(analysis.result.diagnostics.missing_evidence[:12]),
        },
        "elapsed_s": round(elapsed, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N cases (smoke tests)")
    parser.add_argument("--only", type=str, default=None,
                        help="run only this case id")
    parser.add_argument("--provider", type=str, default="mistral",
                        choices=("mistral", "zai"))
    parser.add_argument("--time-budget", type=float, default=None,
                        help="stop cleanly after this many seconds (resumable)")
    args = parser.parse_args()

    started_at = time.time()
    rows = load_firewalled_rows()
    if args.only:
        rows = [row for row in rows if row["id"] == args.only]
    elif args.limit:
        rows = rows[: args.limit]

    progress_path = OUT_DIR / "baseline_attemptA_progress.json"
    cache_path = OUT_DIR / f"baseline_attemptA_llm_cache_{args.provider}.json"
    out = load_progress(progress_path)
    done = {row["case_id"] for row in out}

    backend = build_backend(cache_path, provider=args.provider)
    guardian = b4h_sound_v2_guardian(backend)

    for firewalled in rows:
        case_id = firewalled["id"]
        if case_id in done:
            continue
        if args.time_budget is not None and time.time() - started_at > args.time_budget:
            print(f"TIME BUDGET EXHAUSTED before {case_id}; "
                  f"{len(out)} cases done — rerun to resume", flush=True)
            break
        # Attempt A: direct stuffing, nothing invented.
        case_input = E2ECaseInput(
            case_id=case_id,
            family="",
            system_policy=firewalled["prompt"],
            user_request="",
            history=(),
            target_response=firewalled["response"],
        )
        started = time.time()
        try:
            analysis = guardian.analyze_e2e_v1(case_input)
            record = row_of(analysis, case_input, time.time() - started)
        except Exception as error:  # noqa: BLE001 - a crash is itself a blocker datum
            record = {
                "case_id": case_id, "arm": "B4h-sound-v2", "core_status": "EXECUTION_ERROR",
                "binary": None, "used_fallback": True, "certificate_valid": None,
                "worlds": 0, "required_worlds": 0, "frontend_failures": [],
                "policy_reading_count": 0, "goal_contract_count": 0,
                "component_summary": {},
                "diagnostics": {"primary": "EXECUTION_ERROR", "contributing": [],
                                "missing_evidence": [f"{type(error).__name__}:{str(error)[:300]}"]},
                "elapsed_s": round(time.time() - started, 2),
            }
        record["blockers"] = classify_blockers(record, case_input)
        out.append(record)
        save_progress(progress_path, out)
        print(f"{case_id}: {record['core_status']} blockers={record['blockers'][:3]} "
              f"({record['elapsed_s']}s)", flush=True)

    # Summary
    from collections import Counter

    status_counts = Counter(row["core_status"] for row in out)
    blocker_counts = Counter()
    for row in out:
        for blocker in row["blockers"]:
            blocker_counts[blocker.split(":")[0]] += 1
    summary = {
        "attempt": "A_direct_stuffing",
        "provider": args.provider,
        "model": PROVIDERS[args.provider]["model"],
        "cases": len(out),
        "status_counts": dict(status_counts),
        "blocker_counts": dict(blocker_counts),
        "live_llm_calls": backend.live_calls,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "baseline_attemptA_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import json  # noqa: E402 - used in the summary print

    main()

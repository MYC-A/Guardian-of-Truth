#!/usr/bin/env python3
"""AI Journey Guardian competition entrypoint for B4h-sound-v2 (e2e vnext).

External interface (competition contract):
    python scripts/predict_e2e_competition.py \
        --input <path_to_test.csv|parquet|jsonl> \
        --output <path_to_predictions.csv> \
        [--audit <audit.jsonl>] [--run-report <report.json>]

Output: CSV with columns id,label (label in {0,1}) — the olympiad format.

Gold firewall (invariant): only the columns id/prompt/response are read from
the input; every other column (label, explanation, ...) is physically dropped
before inference; ``id`` never influences the semantic decision (output
joining only).

Arms:
    C1  B4h-sound-v2 + manual/oracle T1 (diagnostic ceiling; uses
        contracts/tool_effects_v1.json where tools match — never
        competition-realistic)
    C2  B4h-sound-v2 + prompt-derived only (MAIN ARM: everything comes from
        the prompt itself; T2 proposals are untrusted semantic candidates)
    C3  B4h-sound-v2 + no tool semantics (transport facts, invocation,
        schema/arguments, literal history evidence only; T2 disabled)

Backend:
    offline  no network: every LLM proposal is a MISS (frontends fail ->
             UNRESOLVED; mechanical/transport checks still run)
    live     BAI provider through Guardian's ChatClient with a
             content-addressed cache for exact reproducibility

Mapping proof status -> competition label (frozen adapter, COMPETITION mode):
    PROVED_ERROR -> 1, PROVED_NO_ERROR -> 0, INCONSISTENT -> 1,
    UNRESOLVED -> 0 (never a proof of correctness; audit records it).
A crashed case is UNRESOLVED (label 0), never a fake verdict.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.vnext.adapters import AdapterMode, adapt  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import (E2ECachingBackend,  # noqa: E402
                                                 build_live_backend)
from guardian_truth.vnext.e2e.competition_adapter_v1 import (  # noqa: E402
    CompetitionCase, load_manual_t1_registry, parse_competition_case,
    parse_response_calls, to_e2e_case)
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS  # noqa: E402
from guardian_truth.vnext.tools import ContractRegistry  # noqa: E402

B4H_ARM = E2EArmConfig("B4h", ("h0_hist",), ("conservative",))


class OfflineMissBackend:
    """Offline backend: every proposal is a transport MISS (no network)."""

    def __init__(self):
        self.misses = 0
        self.receipts = []

    def propose(self, task, payload, schema):
        from guardian_truth.vnext.semantic import Proposal
        self.misses += 1
        return Proposal(None, "ERROR", "NOT_EVALUATED", "OFFLINE_MISS")


def read_input_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".parquet":
        import pandas as pd
        return pd.read_parquet(path).to_dict("records")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def firewall_rows(rows: list[dict]) -> list[dict]:
    """GOLD FIREWALL: keep exactly id/prompt/response; drop everything else."""
    kept = []
    for row in rows:
        missing = [k for k in ("id", "prompt", "response") if k not in row]
        if missing:
            raise ValueError(f"row missing required columns {missing}: {row!r}")
        kept.append({"id": str(row["id"]), "prompt": str(row["prompt"]), "response": str(row["response"])})
    return kept


def build_guardian(arm: str, backend, manual_registry: ContractRegistry | None):
    registry = manual_registry if arm == "C1" else ContractRegistry(())
    enable_t2 = arm != "C3"
    return GuardianE2EV1(backend, registry=registry, arm=B4H_ARM, max_worlds=4096,
                         adapter_mode=AdapterMode.COMPETITION,
                         semantics=SEMANTICS_ARMS["B3"], enable_t2=enable_t2)


def analyze_case(guardian: GuardianE2EV1, comp: CompetitionCase, arm: str) -> dict:
    started = time.time()
    try:
        case = to_e2e_case(comp)
        analysis = guardian.analyze_e2e_v1(case)
        decision = adapt(analysis.result, mode=AdapterMode.COMPETITION)
        record = {
            "id": comp.case_id,
            "core_status": analysis.result.status.value,
            "binary_label": decision.binary_label,
            "used_fallback": decision.used_fallback,
            "certificate_valid": bool(analysis.result.certificate_check
                                      and analysis.result.certificate_check.valid)
            if analysis.result.certificate_check else None,
            "worlds": analysis.world_count, "required_worlds": analysis.required_worlds,
            "frontend_failures": [{"component": n, "kind": k} for n, k, _ in analysis.frontend_statuses],
            "policy_reading_count": len(analysis.policy_readings),
            "goal_contract_count": len(analysis.goal_contracts),
            "component_summary": dict(analysis.component_summary),
            "diagnostics": {"primary": analysis.result.diagnostics.primary_reason.value
                            if analysis.result.diagnostics.primary_reason else None,
                            "contributing": [r.value for r in analysis.result.diagnostics.contributing_reasons],
                            "missing_evidence": list(analysis.result.diagnostics.missing_evidence[:8])},
            "target_tool_calls": [{"tool": t, "arguments_raw": j}
                                  for t, j in parse_response_calls(comp.target_response_body
                                                                   if comp.target_response_body else "")],
            "elapsed_s": round(time.time() - started, 3),
            "error": None,
        }
        return record
    except Exception as error:  # crashed case = UNRESOLVED, never a fake verdict
        case_id = getattr(comp, "case_id", "UNKNOWN")
        return {"id": case_id, "core_status": "UNRESOLVED", "binary_label": 0,
                "used_fallback": True, "certificate_valid": False, "worlds": 0,
                "required_worlds": 0, "frontend_failures": [], "policy_reading_count": 0,
                "goal_contract_count": 0, "component_summary": {},
                "diagnostics": {"primary": "EXECUTION_ERROR",
                                "contributing": [],
                                "missing_evidence": [f"{type(error).__name__}:{str(error)[:300]}"]},
                "target_tool_calls": [], "elapsed_s": round(time.time() - started, 3),
                "error": f"{type(error).__name__}:{str(error)[:300]}"}



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--arm", choices=("C1", "C2", "C3"), default="C2")
    parser.add_argument("--backend", choices=("offline", "live", "local"), default="offline",
                        help="offline=no network (all proposals MISS); live=BAI provider; "
                             "local=OpenAI-compatible local proxy (research diagnostics)")
    parser.add_argument("--cache", type=Path, default=None,
                        help="content-addressed proposal cache (live backend)")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--manual-t1", type=Path, default=ROOT / "contracts" / "tool_effects_v1.json")
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()

    rows = firewall_rows(read_input_rows(args.input))
    if args.max_cases:
        rows = rows[:args.max_cases]

    if args.backend == "live":
        backend = build_live_backend(env_path=args.env_file, cache_path=args.cache)
    elif args.backend == "local":
        # Research-diagnostic backend: local OpenAI-compatible proxy (e.g.
        # scripts/zai_local_proxy.mjs). NOT competition-legal (external API);
        # used only to run the audit arms while the frozen BAI account is out
        # of credit. Same composition as build_live_backend (JsonExtract +
        # caching, response_format_mode none, 2048 output tokens).
        import os
        os.environ.setdefault("GUARDIAN_LOCAL_BASE_URL", "http://127.0.0.1:8010/v1")
        os.environ.setdefault("GUARDIAN_LOCAL_API_KEY", "local-proxy")
        from guardian_truth.llm_client import ChatClient, ClientConfig
        from guardian_truth.runtime import provider_config
        from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend
        config = provider_config(ClientConfig(response_format_mode="none", timeout_seconds=240.0),
                                  "local")
        inner = JsonExtractBackend(ChatClient(config), interval_seconds=0.5)
        backend = E2ECachingBackend(inner, cache_path=args.cache)
    else:
        backend = E2ECachingBackend(OfflineMissBackend(), cache_path=None)

    base_guardian = None if args.arm == "C1" else build_guardian(args.arm, backend, None)
    manual_coverage = {}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    audit_stream = args.audit.open("w", encoding="utf-8") if args.audit else None
    started = time.time()
    counts = {"rows": 0, "status_counts": {}, "fallbacks": 0, "certificate_valid": 0}
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "label"])
        writer.writeheader()
        for row in rows:
            comp = parse_competition_case(row["id"], row["prompt"], row["response"])
            if args.arm == "C1":
                registry, coverage = load_manual_t1_registry(args.manual_t1, catalog=comp.catalog)
                manual_coverage[row["id"]] = coverage
                guardian = build_guardian(args.arm, backend, registry)
            else:
                guardian = base_guardian
            record = analyze_case(guardian, comp, args.arm)
            writer.writerow({"id": row["id"], "label": int(record["binary_label"])})
            stream.flush()
            counts["rows"] += 1
            status = record["core_status"]
            counts["status_counts"][status] = counts["status_counts"].get(status, 0) + 1
            counts["fallbacks"] += int(bool(record["used_fallback"]))
            counts["certificate_valid"] += int(bool(record["certificate_valid"]))
            if audit_stream:
                if args.arm == "C1":
                    record["manual_t1_coverage"] = manual_coverage.get(row["id"], [])
                audit_stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                audit_stream.flush()
    if audit_stream:
        audit_stream.close()

    if args.run_report:
        counts.update(arm=args.arm, backend=args.backend, seconds=round(time.time() - started, 3),
                      live_calls=getattr(backend, "live_calls", 0),
                      cache_hits=sum(1 for r in getattr(backend, "receipts", [])
                                     if r.get("cache_hit")),
                      input=str(args.input))
        args.run_report.parent.mkdir(parents=True, exist_ok=True)
        args.run_report.write_text(json.dumps(counts, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

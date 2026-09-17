"""Mode runner (directive §17-§20): R1 (competition prompt only) and R2
(structural only) over the 46 public valid cases.

- Predictions are produced WITHOUT reading labels (gold firewall) and saved
  with SHA256 seals BEFORE any scoring (§18).
- Per-case audit fields (§19: environment, target, required premises,
  witnesses, missing information) are captured into the progress records and
  later assembled into cases.jsonl by real_valid_assemble.py.
- Internal statuses (PROVED_ERROR/PROVED_NO_ERROR/UNRESOLVED/INCONSISTENT)
  are preserved (§20); the binary label uses the repo's own frozen product
  adapter in COMPETITION mode (PROVED_ERROR->1, PROVED_NO_ERROR->0,
  INCONSISTENT->1, UNRESOLVED->0) — a pre-existing repo decision, not a new
  one, fixed BEFORE any gold is unsealed.

Modes:
  R1 = competition adapter + prompt-derived catalog/schemas + T2 untrusted
       effect proposals enabled (the frozen B4h-sound-v2 behavior).
  R2 = same input decomposition, enable_t2=False (no untrusted semantic
       effect proposals; structural evidence only).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

from real_valid_adapter import competition_case, parse_tool_catalog
from real_valid_common import (OUT_DIR, PROVIDERS, REPO_ROOT, build_backend,
                               load_firewalled_rows, load_progress, save_progress)

import sys

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS  # noqa: E402
from guardian_truth.parsing import parse_events  # noqa: E402


def guardian_for_mode(backend, mode: str, *, catalog_conformance: bool = True,
                      schemas: dict | None = None) -> GuardianE2EV1:
    """B4h-sound-v2 frozen configuration; R2 disables T2 proposals only.
    catalog_conformance: session B fix iteration 1 (deterministic prompt-
    grounded obligations over RESPONSE calls; flag-gated, default OFF in the
    library itself)."""
    from guardian_truth.vnext.tools import ContractRegistry
    from dataclasses import replace
    registry = ContractRegistry((), schemas=schemas or {})
    # Session B fix iterations: B3 semantics + REP-08 must-act abstention
    # (iteration 2). Flag lives in E2ESemantics; default OFF keeps the frozen
    # B0..B4 arms byte-identical.
    semantics = replace(SEMANTICS_ARMS["B3"], must_act_abstention=True)
    return GuardianE2EV1(
        backend,
        registry=registry,
        arm=E2EArmConfig("B4h-sound-v2", ("h0_hist",), ("conservative",)),
        max_worlds=4096,
        adapter_mode=AdapterMode.COMPETITION,
        enable_t2=(mode != "R2"),
        semantics=semantics,
        catalog_conformance=catalog_conformance,
        goal_format_repair=True,  # session A iteration-1 KEEP fix, adopted
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atom_inventory(analysis) -> list[str]:
    atoms = {}
    for proof in analysis.result.world_proofs:
        for primitive in proof.primitives:
            atoms[primitive.atom.atom_id] = (
                f"{primitive.atom.kind.value}:{primitive.atom.predicate}"
                f"@{primitive.atom.entity.value}:{primitive.atom.time_index}")
    return sorted(atoms.values())


def _false_witnesses(analysis) -> list[str]:
    out = []
    for proof in analysis.result.world_proofs:
        for obligation_id, value in proof.obligation_safety:
            if str(value) == "FALSE":
                out.append(f"{proof.world_id}:{obligation_id}")
    return out[:12]


def _t2_premises(analysis) -> list[dict]:
    records = []
    for effect in analysis.ledger.effects:
        if effect.provenance == "UNTRUSTED_T2_SEMANTIC_PROPOSAL":
            records.append({"predicate": effect.predicate, "value_json": effect.value_json,
                            "event_id": effect.event_id, "origin": effect.provenance})
    return records[:16]


def enrich(firewalled: dict, record: dict, analysis, mode: str) -> dict:
    """§19 audit fields computed from a live analysis object."""
    prompt = firewalled["prompt"]
    meta, schemas = parse_tool_catalog(prompt)
    events = parse_events(prompt, "prompt")
    resp_events = parse_events(firewalled["response"], "response")
    record["input"] = {
        "prompt_sha256": _sha256(prompt),
        "response_sha256": _sha256(firewalled["response"]),
        "prompt_chars": len(prompt),
        "response_chars": len(firewalled["response"]),
    }
    record["environment"] = {
        "tool_count": len(meta),
        "tool_names": sorted(item["name"] for item in meta),
        "schema_available": bool(schemas),
        "descriptions_available": all(s.get("description") for s in schemas),
        "history_call_events": sum(1 for e in events if e.kind == "call"),
    }
    record["target"] = {
        "tool_calls": [f"{e.name}: {e.text[:140]}" for e in resp_events if e.kind == "call"],
        "text_spans": [e.text[:200] for e in resp_events if e.kind == "text"],
    }
    record["required_premises"] = _atom_inventory(analysis)
    record["t2_premises"] = _t2_premises(analysis)
    record["false_witnesses"] = _false_witnesses(analysis)
    record["trusted_effect_count"] = sum(
        1 for effect in analysis.ledger.effects if effect.contract_sha256)
    return record


def base_record(case_id: str, started: float, error: str | None = None) -> dict:
    return {
        "case_id": case_id,
        "core_status": "EXECUTION_ERROR" if error else None,
        "binary": None,
        "used_fallback": True,
        "certificate_valid": None,
        "worlds": 0,
        "required_worlds": 0,
        "policy_reading_count": 0,
        "goal_contract_count": 0,
        "frontend_failures": [],
        "component_summary": {},
        "diagnostics": {"primary": "EXECUTION_ERROR", "contributing": [],
                        "missing_evidence": [error or ""]},
        "elapsed_s": round(time.time() - started, 2),
    }


def run_mode(mode: str, *, provider: str, time_budget: float | None, limit: int | None = None,
             catalog: bool = True, dir_suffix: str = "") -> None:
    started_at = time.time()
    rows = load_firewalled_rows()
    if limit:
        rows = rows[:limit]

    mode_dir = OUT_DIR / (mode + dir_suffix)
    mode_dir.mkdir(parents=True, exist_ok=True)
    progress_path = mode_dir / f"{mode}_progress.json"
    cache_path = OUT_DIR / mode / f"{mode}_llm_cache_{provider}.json"
    out = load_progress(progress_path)
    done = {row["case_id"] for row in out}

    backend = build_backend(cache_path, provider=provider)

    for firewalled in rows:
        case_id = firewalled["id"]
        if case_id in done:
            continue
        if time_budget is not None and time.time() - started_at > time_budget:
            print(f"TIME BUDGET EXHAUSTED before {case_id}; {len(out)} done — rerun to resume", flush=True)
            break
        case = competition_case(firewalled)
        _, schemas_list = parse_tool_catalog(firewalled["prompt"])
        case_schemas = {schema["name"]: schema for schema in schemas_list}
        guardian = guardian_for_mode(backend, mode, schemas=case_schemas,
                                     catalog_conformance=catalog)
        started = time.time()
        try:
            analysis = guardian.analyze_e2e_v1(case)
            record = base_record(case_id, started)
            check = analysis.result.certificate_check
            record.update({
                "core_status": analysis.result.status.value,
                "binary": analysis.product_decision.binary_label,
                "used_fallback": analysis.product_decision.used_fallback,
                "certificate_valid": bool(check and check.valid) if check else None,
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
                    "missing_evidence": list(analysis.result.diagnostics.missing_evidence[:12]),
                },
            })
            record = enrich(firewalled, record, analysis, mode)
        except Exception as failure:  # noqa: BLE001 - crash is UNRESOLVED, never a fake verdict
            error = f"{type(failure).__name__}:{str(failure)[:300]}"
            record = base_record(case_id, started, error)
        out.append(record)
        save_progress(progress_path, out)
        print(f"[{mode}] {case_id}: {record['core_status']} binary={record['binary']} "
              f"cert={record['certificate_valid']} ({record['elapsed_s']}s)", flush=True)

    if len(out) == len(rows):
        seal_mode(mode, provider, out, dir_suffix)


def seal_mode(mode: str, provider: str, out: list, dir_suffix: str = "") -> None:
    """§18: predictions sealed with SHA256 BEFORE any gold is read."""
    mode_dir = OUT_DIR / (mode + dir_suffix)
    predictions_path = mode_dir / f"{mode}_predictions.csv"
    with open(predictions_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "label"])
        for row in sorted(out, key=lambda item: item["case_id"]):
            writer.writerow([row["case_id"], row["binary"] if row["binary"] is not None else 0])
    digest = hashlib.sha256(predictions_path.read_bytes()).hexdigest()
    seal = {
        "mode": mode,
        "provider": provider,
        "model": PROVIDERS[provider]["model"],
        "architecture": "B4h-sound-v2 @ 315bee335a467476732b47e1e7f412097222cd3b",
        "arm": "h0_hist + conservative, B3 semantics",
        "adapter": "competition adapter v1 (scripts/real_valid_adapter.py); "
                   "binary = frozen product adapter COMPETITION mode",
        "predictions_sha256": digest,
        "predictions_file": str(predictions_path.name),
        "case_count": len(out),
        "core_statuses": {row["case_id"]: row["core_status"] for row in out},
        "gold_joined": False,
        "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    seal_path = mode_dir / f"{mode}_prediction_seal.json"
    if seal_path.exists():
        existing = json.loads(seal_path.read_text(encoding="utf-8"))
        if existing.get("predictions_sha256") != digest:
            raise SystemExit(f"seal mismatch for {mode}: predictions changed after sealing")
        print(f"[{mode}] seal already present and matches")
        return
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{mode}] SEALED {len(out)} predictions, sha256={digest[:16]}...")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("R1", "R2"))
    parser.add_argument("--provider", default="mistral", choices=("mistral", "zai"))
    parser.add_argument("--time-budget", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seal-only", action="store_true")
    parser.add_argument("--no-catalog", action="store_true",
                        help="control run: same input decomposition, catalog axis OFF")
    parser.add_argument("--dir-suffix", default="")
    args = parser.parse_args()
    if args.seal_only:
        progress = load_progress(OUT_DIR / (args.mode + args.dir_suffix) / f"{args.mode}_progress.json")
        seal_mode(args.mode, args.provider, progress, args.dir_suffix)
        return
    run_mode(args.mode, provider=args.provider, time_budget=args.time_budget, limit=args.limit,
             catalog=not args.no_catalog, dir_suffix=args.dir_suffix)


if __name__ == "__main__":
    main()

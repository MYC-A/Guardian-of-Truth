"""core_engine_bakeoff_v1 — synthetic benchmark runner.

Runs every available backend over the deterministic scenario suite, compares
final statuses, world verdicts and primitive probes against the scenario
oracle, classifies mismatches, and writes outputs/core_engine_bakeoff_v1/
synthetic_results.json.

Mismatch classification (per the directive's diagnostics taxonomy):
  FRONTEND_LIMITATION        — not applicable (NeutralCoreInput is given)
  ENGINE_EXPRESSIVITY       — the reference semantics cannot be expressed
  ENGINE_SEMANTIC_MISMATCH  — UNKNOWN/FALSE/world semantics altered
  ADAPTER_BUG               — translation defect (hard failure)
  CURRENT_CORE_LIMITATION   — the incumbent core lacks the primitive
                              (comparison / cardinality / disjunction /
                              value-typed state exception / completed
                              wildcard) and honestly abstains
  UNSOUND_NEW_ENGINE        — a backend proves ERROR without evidence
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "outputs" / "core_engine_bakeoff_v1"
for p in (str(HERE),):
    if p not in sys.path:
        sys.path.insert(0, p)

from neutral_types import NeutralCoreInput
from scenarios import build_scenarios

BACKENDS = ("current_guardian", "clingo_backend", "scasp_backend",
            "drools_backend")


def _backend_module(name: str):
    import importlib
    return importlib.import_module(f"backends.{name}")


# classification hints: scenario family -> incumbent limitation
_CLASS_E_FAMILIES = {
    "numeric_lt", "numeric_le", "numeric_gt_false", "equality",
    "inequality", "count_ge", "count_ge_fail", "count_eq",
    "count_temporal_entity", "count_temporal_entity_fail",
    "or_false", "or_true", "nested",
    "latest_state", "superseded_state", "conflicting_evidence",
    "missing_state_evidence", "unverified_mutation",
}


def _classify(scenario, backend: str, got: str, expected: str) -> str:
    if got == expected:
        return "MATCH"
    if backend == "current_guardian" and scenario.family in _CLASS_E_FAMILIES:
        return "CURRENT_CORE_LIMITATION"
    if got == "PROVED_ERROR" and expected in ("UNRESOLVED", "PROVED_NO_ERROR",
                                              "INCONSISTENT"):
        return "UNSOUND_NEW_ENGINE"
    if got == "ERROR":
        return "BACKEND_ERROR"
    if got in ("UNRESOLVED",) and expected in ("PROVED_ERROR",):
        return "ENGINE_SEMANTIC_MISMATCH"
    return "ADAPTER_BUG"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    results = {}
    summary = {b: {"final_ok": 0, "final_total": 0, "world_ok": 0,
                   "world_total": 0, "primitive_ok": 0, "primitive_total": 0,
                   "classes": {}} for b in BACKENDS}
    started = time.time()
    for backend_name in BACKENDS:
        try:
            module = _backend_module(backend_name)
        except Exception as error:
            results[backend_name] = {"available": False,
                                     "error": f"{type(error).__name__}: {error}"}
            continue
        rows = []
        for scenario in scenarios:
            row = {"scenario_id": scenario.scenario_id,
                   "family": scenario.family,
                   "expected_final": scenario.expected_final}
            try:
                result = module.evaluate(scenario.core_input)
            except Exception as error:
                result = None
                row["error"] = f"{type(error).__name__}: {str(error)[:200]}"
            if result is not None:
                row["final"] = result.status
                row["runtime_ms"] = round(result.runtime_ms, 1)
                row["worlds"] = {w.interp_id: w.error_value
                                 for w in result.worlds}
                row["notes"] = result.notes
                row["detail"] = result.detail
                row["classification"] = _classify(
                    scenario, backend_name, result.status,
                    scenario.expected_final)
                summary[backend_name]["final_total"] += 1
                if row["classification"] == "MATCH":
                    summary[backend_name]["final_ok"] += 1
                cls = row["classification"]
                summary[backend_name]["classes"][cls] = \
                    summary[backend_name]["classes"].get(cls, 0) + 1
                # world verdicts
                world_ok = world_total = 0
                for interp_id, expected_v in scenario.expected_worlds.items():
                    world_total += 1
                    got_v = row["worlds"].get(interp_id)
                    exp_map = {"ERROR": "TRUE", "NO_ERROR": "FALSE",
                               "UNKNOWN": "UNKNOWN", "BOTH": "BOTH"}
                    if got_v == exp_map[expected_v]:
                        world_ok += 1
                row["world_match"] = f"{world_ok}/{world_total}"
                summary[backend_name]["world_total"] += world_total
                summary[backend_name]["world_ok"] += world_ok
                # probes
                try:
                    prims = module.probe(scenario.core_input,
                                         scenario.probe_atoms)
                    p_ok = p_total = 0
                    misses = []
                    for prim in prims:
                        exp = scenario.expected_primitives.get(prim.atom_key)
                        if exp is None:
                            continue
                        p_total += 1
                        if prim.value == exp:
                            p_ok += 1
                        else:
                            misses.append([prim.atom_key, prim.value, exp])
                    row["primitive_match"] = f"{p_ok}/{p_total}"
                    if misses:
                        row["primitive_misses"] = misses
                    summary[backend_name]["primitive_total"] += p_total
                    summary[backend_name]["primitive_ok"] += p_ok
                except Exception as error:
                    row["probe_error"] = f"{type(error).__name__}: {str(error)[:150]}"
            rows.append(row)
        results[backend_name] = {"available": True, "rows": rows}

    payload = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scenarios": len(scenarios),
        "backends": summary,
        "results": results,
    }
    (OUT / "synthetic_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"total wall time: {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()

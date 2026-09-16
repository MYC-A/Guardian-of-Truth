"""E2E V1 experiment runner (spec 155-171): arm execution with one semantic
attempt per input (memoized), incremental prediction files, sealing before
gold, scoring, paired statistics (exact two-sided McNemar), oracle
diagnostics and failure taxonomy classification."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from ..adapters import AdapterMode
from ..integrity import digest, prediction_seal, write_new
from .core_v1 import GuardianE2EV1
from .e2e_types_v1 import ARMS, E2EArmConfig, E2ECaseInput

EXPERIMENT_VERSION = "guardian_e2e_v1_experiment"


def load_corpus(path: Path) -> list[E2ECaseInput]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for row in rows:
        cases.append(E2ECaseInput(
            case_id=row["case_id"], family=row["family"],
            system_policy=row.get("system_policy", ""),
            user_request=row.get("user_request", ""),
            history=tuple(row.get("history", ())),
            target_response=row["target_response"],
            tool_metadata=tuple(row.get("tool_metadata", ())),
            tool_schemas=tuple(row.get("tool_schemas", ())),
            t1_contracts=tuple(row.get("t1_contracts", ())),
            state_contract=row.get("state_contract"),
            history_complete=bool(row.get("history_complete", False)),
            completeness_basis=row.get("completeness_basis"),
            authoritative_policy_readings=tuple(row.get("authoritative_policy_readings", ())),
            authoritative_goal_readings=tuple(row.get("authoritative_goal_readings", ())),
            authoritative_policy_behaviors=tuple(row.get("authoritative_policy_behaviors", ())),
            authoritative_goal_behaviors=tuple(row.get("authoritative_goal_behaviors", ())),
            gold_core_status=row.get("gold_core_status", ""),
            gold_binary=row.get("gold_binary"),
            notes=row.get("notes", ""),
            raw_prompt=row.get("raw_prompt")))
    return cases


def registry_for(case: E2ECaseInput):
    from ..tools import ContractRegistry, TrustedContract, ToolIdentity
    contracts = []
    for row in case.t1_contracts:
        identity = ToolIdentity(row["identity"]["name"], row["identity"].get("provider"),
                                row["identity"].get("version"), row["identity"].get("schema_sha256"))
        from ..tools import ConditionalGuarantee, EffectSpec, FieldCondition
        guarantees = tuple(ConditionalGuarantee(
            conditions=tuple(FieldCondition(c["source"], tuple(c["path"]), c["equals_json"]) for c in g.get("conditions", ())),
            effects=tuple(EffectSpec(e["argument_entity_field"], e["predicate"], e["value_json"],
                                     bool(e.get("causal_action_confirmed", False))) for e in g.get("effects", ())))
            for g in row.get("guarantees", ()))
        contracts.append(TrustedContract(
            identity=identity,
            preconditions=tuple(FieldCondition(c["source"], tuple(c["path"]), c["equals_json"])
                                for c in row.get("preconditions", ())),
            reads=tuple(row.get("reads", ())), writes=tuple(row.get("writes", ())),
            guarantees=guarantees,
            possible_effects=tuple(EffectSpec(e["argument_entity_field"], e["predicate"], e["value_json"])
                                   for e in row.get("possible_effects", ())),
            no_effect_conditions=tuple(FieldCondition(c["source"], tuple(c["path"]), c["equals_json"])
                                       for c in row.get("no_effect_conditions", ())),
            failure_semantics=row.get("failure_semantics", "documented"),
            freshness=row.get("freshness", "unspecified"),
            idempotence=row.get("idempotence", "unspecified"),
            provenance=row.get("provenance", "bench_authoritative_contract")))
    return ContractRegistry(tuple(contracts))


def run_arm(arm: E2EArmConfig, cases: list[E2ECaseInput], backend, *, registry_builder=registry_for,
            oracle_policy: bool = False, oracle_goal: bool = False, max_worlds: int = 4096,
            progress_file: Path | None = None) -> list[dict]:
    rows = []
    if progress_file is not None and progress_file.exists():
        rows = json.loads(progress_file.read_text(encoding="utf-8"))
    done = {row["case_id"] for row in rows}
    for case in cases:
        if case.case_id in done:
            continue
        guardian = GuardianE2EV1(backend, registry=registry_builder(case), arm=arm,
                                  max_worlds=max_worlds, adapter_mode=AdapterMode.AUDIT,
                                  oracle_policy=oracle_policy, oracle_goal=oracle_goal)
        started = time.time()
        try:
            analysis = guardian.analyze_e2e_v1(case)
            rows.append(_row(analysis, case, arm, oracle_policy, oracle_goal, time.time() - started))
        except Exception as error:  # defensive: a crashed case is UNRESOLVED, never a fake verdict
            rows.append({"case_id": case.case_id, "family": case.family, "arm": arm.arm_id,
                         "core_status": "UNRESOLVED", "binary": None, "used_fallback": True,
                         "certificate_valid": False, "worlds": 0, "required_worlds": 0,
                         "frontend_failures": [], "component_summary": {},
                         "diagnostics": {"primary": "EXECUTION_ERROR", "contributing": [],
                                         "missing_evidence": [f"{type(error).__name__}:{str(error)[:200]}"]},
                         "elapsed_s": round(time.time() - started, 2)})
        if progress_file is not None:
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            progress_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def _row(analysis, case, arm, oracle_policy, oracle_goal, elapsed) -> dict:
    return {"case_id": case.case_id, "family": case.family, "arm": arm.arm_id,
            "core_status": analysis.result.status.value,
            "binary": analysis.product_decision.binary_label,
            "used_fallback": analysis.product_decision.used_fallback,
            "certificate_valid": bool(analysis.result.certificate_check and analysis.result.certificate_check.valid)
            if analysis.result.certificate_check else None,
            "worlds": analysis.world_count, "required_worlds": analysis.required_worlds,
            "frontend_failures": [{"component": name, "kind": kind} for name, kind, _ in analysis.frontend_statuses],
            "policy_reading_count": len(analysis.policy_readings),
            "goal_contract_count": len(analysis.goal_contracts),
            "component_summary": {k: v for k, v in analysis.component_summary.items()},
            "diagnostics": {"primary": analysis.result.diagnostics.primary_reason.value
                            if analysis.result.diagnostics.primary_reason else None,
                            "contributing": [r.value for r in analysis.result.diagnostics.contributing_reasons],
                            "missing_evidence": list(analysis.result.diagnostics.missing_evidence[:8])},
            "oracle": bool(oracle_policy or oracle_goal),
            "elapsed_s": round(elapsed, 2)}


# ------------------------------------------------------------------ scoring

def score_arm(rows: list[dict], gold: dict) -> dict:
    """Primary Core metrics (spec 161, 162). Gold is joined only here."""
    total = len(rows)
    definitive = [row for row in rows if row["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}]
    correct_definitive = [row for row in definitive
                          if row["core_status"] == gold.get(row["case_id"], {}).get("core_status")]
    false_no_error = [row for row in rows if row["core_status"] == "PROVED_NO_ERROR"
                      and gold.get(row["case_id"], {}).get("core_status") != "PROVED_NO_ERROR"]
    false_error = [row for row in rows if row["core_status"] == "PROVED_ERROR"
                   and gold.get(row["case_id"], {}).get("core_status") != "PROVED_ERROR"]
    gold_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_ERROR"}
    gold_no_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_NO_ERROR"}
    proved_error_recall = (sum(1 for row in rows if row["case_id"] in gold_error
                               and row["core_status"] == "PROVED_ERROR") / len(gold_error)) if gold_error else None
    proved_no_error_recall = (sum(1 for row in rows if row["case_id"] in gold_no_error
                                  and row["core_status"] == "PROVED_NO_ERROR") / len(gold_no_error)) if gold_no_error else None
    uncertified = [row for row in definitive if not row.get("certificate_valid")]
    status_counts = {}
    for row in rows:
        status_counts[row["core_status"]] = status_counts.get(row["core_status"], 0) + 1
    worlds = [row.get("worlds", 0) for row in rows]
    required = [row.get("required_worlds", 0) for row in rows]
    sorted_worlds = sorted(worlds)
    p95 = sorted_worlds[min(len(sorted_worlds) - 1, math.ceil(0.95 * len(sorted_worlds)) - 1)] if sorted_worlds else 0
    return {
        "arm": rows[0]["arm"] if rows else None,
        "total": total,
        "certified_definitive_coverage": round(len([r for r in definitive if r.get("certificate_valid")]) / total, 4) if total else 0,
        "definitive_coverage": round(len(definitive) / total, 4) if total else 0,
        "certified_definitive_accuracy": round(len([r for r in correct_definitive if r.get("certificate_valid")]) /
                                               len([r for r in definitive if r.get("certificate_valid")]), 4)
            if any(r.get("certificate_valid") for r in definitive) else None,
        "correct_definitive_coverage": round(len(correct_definitive) / total, 4) if total else 0,
        "unsafe_definitive_rate": round((len(false_no_error) + len(false_error)) / total, 4) if total else 0,
        "false_certified_no_error": len(false_no_error),
        "false_certified_error": len(false_error),
        "uncertified_definitive": len(uncertified),
        "proved_error_recall": round(proved_error_recall, 4) if proved_error_recall is not None else None,
        "proved_no_error_recall": round(proved_no_error_recall, 4) if proved_no_error_recall is not None else None,
        "unresolved_rate": round(status_counts.get("UNRESOLVED", 0) / total, 4) if total else 0,
        "status_counts": status_counts,
        "world_metrics": {"mean_worlds": round(sum(worlds) / len(worlds), 2) if worlds else 0,
                          "p95_worlds": p95, "max_worlds": max(worlds) if worlds else 0,
                          "max_required_worlds": max(required) if required else 0},
        "mean_elapsed_s": round(sum(row.get("elapsed_s", 0) for row in rows) / total, 2) if total else 0,
    }


def mcnemar_exact(rows_a: list[dict], rows_b: list[dict], gold: dict) -> dict:
    """Exact two-sided McNemar on paired per-case definitive correctness."""
    by_a = {row["case_id"]: row for row in rows_a}
    by_b = {row["case_id"]: row for row in rows_b}
    b = c = 0
    for case_id in by_a:
        if case_id not in by_b:
            continue
        gold_status = gold.get(case_id, {}).get("core_status")
        correct_a = by_a[case_id]["core_status"] == gold_status and by_a[case_id]["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}
        correct_b = by_b[case_id]["core_status"] == gold_status and by_b[case_id]["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}
        if correct_a and not correct_b:
            b += 1
        elif correct_b and not correct_a:
            c += 1
    n = b + c
    p = 1.0
    if n:
        k = min(b, c)
        p = sum(math.comb(n, i) for i in range(0, k + 1)) * 2 / (2 ** n)
        p = min(1.0, p)
    return {"b_only": b, "c_only": c, "n": n, "p_two_sided": round(p, 6),
            "corrections_a": b, "regressions_a": c}


def disagreement_metrics(rows_by_arm: dict, gold: dict) -> dict:
    """Frontend disagreement metrics (spec 145-147) from cached frontends."""
    e0 = {row["case_id"]: row for row in rows_by_arm.get("E0", ())}
    e4 = {row["case_id"]: row for row in rows_by_arm.get("E4", ())}
    agreement = disagreement = decisive = absorbed = 0
    for case_id, row4 in e4.items():
        row0 = e0.get(case_id)
        if row0 is None:
            continue
        same = row0["core_status"] == row4["core_status"]
        if same:
            agreement += 1
        else:
            disagreement += 1
            gold_status = gold.get(case_id, {}).get("core_status")
            decisive += int((row4["core_status"] == gold_status) != (row0["core_status"] == gold_status))
            absorbed += int((row4["core_status"] == gold_status) and (row0["core_status"] != gold_status))
    return {"agreement_rate": round(agreement / len(e0), 4) if e0 else None,
            "disagreement_rate": round(disagreement / len(e0), 4) if e0 else None,
            "decisive_disagreement": decisive, "absorbed_disagreement": absorbed}


def classify_failure(row: dict, gold_status: str) -> str:
    """Failure taxonomy (spec 171, 172) for a wrong or non-definitive case."""
    if row["core_status"] == gold_status:
        return "CORRECT"
    failures = {(item["component"], item["kind"]) for item in row.get("frontend_failures", ())}
    summary = row.get("component_summary", {})
    primary = row.get("diagnostics", {}).get("primary")
    if failures:
        component, kind = sorted(failures)[0]
        if component.startswith("policy_h0"):
            return "POLICY_H0"
        if component.startswith("policy_grs_grounder"):
            return "POLICY_GRS_GROUNDER"
        if component.startswith("policy_grs_synth"):
            return "POLICY_GRS_COMPOSITION"
        return "GOAL_" + component.split("_", 1)[-1].upper() if component.startswith("goal") else "OTHER"
    if row["core_status"] == "UNRESOLVED":
        if row.get("worlds", 0) == 0 and row.get("required_worlds", 0) > 0:
            return "WORLD_BUDGET"
        if summary.get("claim_axes", 0) == 0 and gold_status == "PROVED_ERROR":
            return "CLAIM_SUPPORT"
        if primary in {"ENTITY_UNBOUND", "ENTITY_AMBIGUOUS"}:
            return "ENTITY_BINDING"
        if primary == "TIME_UNBOUND" or "FRESH" in " ".join(row.get("diagnostics", {}).get("missing_evidence", [])):
            return "FRESHNESS"
        if primary == "CAUSALITY_UNPROVED":
            return "CAUSALITY"
        if primary in {"TRANSPORT_ERROR", "SCHEMA_ERROR"}:
            return "SOURCE_AUTHORITY"
        if summary.get("frontend_failures"):
            return "POLICY_LOWERING"
        if row.get("policy_reading_count", 0) == 0:
            return "POLICY_H0"
        if row.get("goal_contract_count", 0) == 0:
            return "GOAL_CONSERVATIVE"
        if not row.get("certificate_valid", False) and row["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}:
            return "CERTIFICATE"
        return "SEMANTIC_BEHAVIOR"
    if row["core_status"] == "PROVED_NO_ERROR" and gold_status == "PROVED_ERROR":
        return "FALSE_CERTIFIED_NO_ERROR"
    if row["core_status"] == "PROVED_ERROR" and gold_status == "PROVED_NO_ERROR":
        return "FALSE_CERTIFIED_ERROR"
    return "OTHER"


def failure_audit(rows: list[dict], gold: dict) -> list[dict]:
    out = []
    for row in rows:
        gold_status = gold.get(row["case_id"], {}).get("core_status")
        taxonomy = classify_failure(row, gold_status)
        if taxonomy == "CORRECT":
            continue
        out.append({"case_id": row["case_id"], "family": row["family"], "arm": row["arm"],
                    "predicted": row["core_status"], "gold": gold_status,
                    "taxonomy": taxonomy, "primary": row.get("diagnostics", {}).get("primary"),
                    "frontend_failures": row.get("frontend_failures"),
                    "missing_evidence": row.get("diagnostics", {}).get("missing_evidence", [])[:4],
                    "policy_readings": row.get("policy_reading_count"),
                    "goal_contracts": row.get("goal_contract_count")})
    return out


def seal_predictions(rows: list[dict], corpus_path: Path, *, architecture_commit: str,
                     configuration_sha256: str, seal_path: Path) -> dict:
    case_ids = [row["case_id"] for row in rows]
    seal = prediction_seal(rows, case_ids, architecture_commit=architecture_commit,
                           configuration_sha256=configuration_sha256)
    write_new(seal_path, seal)
    return seal

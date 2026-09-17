"""FN-audit deep pipeline trace (directive §9-§10, §17). DIAGNOSTIC ONLY.

For each of the 15 canonical FN cases, captures the FULL pipeline state at
every stage so the first information-loss point can be localized:

  RAW SOURCE -> ADAPTER -> POLICY FRONTEND -> GOAL FRONTEND -> CLAIM FRONTEND
  -> TOOL/STATE EVIDENCE -> BINDING -> LOWERING -> WORLD OBLIGATIONS -> SOLVER
  -> CERTIFICATE -> FINAL STATUS

Also dumps the raw prompt/response/explanation slices needed for the HUMAN
reading pass (directive §9: read the raw case FIRST, before the trace).

Uses the same frozen cache (100% hits, zero live calls). No production change.
"""
from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from real_valid_common import OUT_DIR, build_backend  # noqa: E402
from real_valid_adapter import competition_case, parse_tool_catalog, parse_competition_prompt  # noqa: E402
from real_valid_run import guardian_for_mode  # noqa: E402

AUDIT_DIR = REPO_ROOT / "outputs" / "vnext" / "fn_audit"
TRACE_DIR = AUDIT_DIR / "traces"
WORK_CACHE = AUDIT_DIR / "run_a" / "llm_cache.json"   # the verified replay cache


def as_dict(obj, depth=0):
    """Best-effort recursive serialization of frozen dataclasses."""
    if depth > 8:
        return repr(obj)
    if is_dataclass(obj):
        return {f.name: as_dict(getattr(obj, f.name), depth + 1) for f in fields(obj)}
    if isinstance(obj, tuple):
        return [as_dict(v, depth + 1) for v in obj]
    if isinstance(obj, list):
        return [as_dict(v, depth + 1) for v in obj]
    if isinstance(obj, dict):
        return {str(k): as_dict(v, depth + 1) for k, v in obj.items()}
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    return repr(obj)


def serialize_obligation(obligation):
    atom = obligation.atom
    return {
        "obligation_id": obligation.obligation_id,
        "hypothesis_id": obligation.hypothesis_id,
        "claim_id": obligation.claim_id,
        "must_be_true": obligation.must_be_true,
        "atom": {
            "atom_id": atom.atom_id,
            "kind": atom.kind.value if hasattr(atom.kind, "value") else str(atom.kind),
            "predicate": atom.predicate,
            "entity": str(atom.entity),
            "time_index": atom.time_index,
            "expected_json": atom.expected_json,
            "argument_constraints": [
                {"path": list(c.path), "allowed_json": list(c.allowed_json)}
                for c in atom.argument_constraints],
        },
        "conditions": [
            {"atom_id": c.atom_id, "predicate": c.predicate, "entity": str(c.entity),
             "time_index": c.time_index, "expected_json": c.expected_json,
             "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind)}
            for c in obligation.conditions],
    }


def trace_case(guardian, firewalled, gold_row):
    case_id = firewalled["id"]
    prompt, response = firewalled["prompt"], firewalled["response"]

    # ---- human-reading material (directive §9) ----
    parts = parse_competition_prompt(prompt)
    raw = {
        "case_id": case_id,
        "system_policy": parts["system_policy"][:20000],
        "user_request": parts["user_request"][:8000],
        "history_parts": len(parts["history"]),
        "response": response[:12000],
        "gold_label": int(gold_row["label"]),
        "gold_explanation": str(gold_row["explanation"])[:4000],
    }

    case = competition_case(firewalled)
    _, schemas_list = parse_tool_catalog(prompt)
    case_schemas = {s["name"]: s for s in schemas_list}
    g = guardian_for_mode(guardian, "R1", schemas=case_schemas, catalog_conformance=True)
    analysis = g.analyze_e2e_v1(case)

    # ---- pipeline trace (directive §10) ----
    trace = {"case_id": case_id}

    # policy frontend readings
    trace["policy_readings"] = [
        {"reading_id": r.reading_id, "frontend": r.frontend,
         "unresolved_terms": list(r.unresolved_terms),
         "rules": [
             {"rule_id": rule.rule_id, "kind": rule.kind, "modality": rule.modality,
              "action_key": rule.action_key, "actor": rule.actor, "relation": rule.relation,
              "conditions": [{"key": c.key, "negated": c.negated, "bound": c.bound,
                              "quote": c.quote[:300], "literal_kind": c.literal_kind}
                             for c in rule.conditions],
              "exceptions": [{"key": c.key, "negated": c.negated, "bound": c.bound,
                              "quote": c.quote[:300], "literal_kind": c.literal_kind}
                             for c in rule.exceptions],
              "scope": [[f, list(v)] for f, v in rule.scope],
              "source_quotes": [q[:300] for q in rule.source_quotes],
              "unresolved_terms": list(rule.unresolved_terms),
              "alternatives": list(rule.alternatives)}
             for rule in r.rules]}
        for r in analysis.policy_readings]

    # goal frontend contracts
    trace["goal_contracts"] = [
        {"contract_id": c.contract_id, "frontend": c.frontend,
         "unresolved_terms": list(c.unresolved_terms),
         "frames": [as_dict(f) for f in c.frames]}
        for c in analysis.goal_contracts]

    # claim frontend
    claims = analysis.component_summary.get("claim_axes", 0)
    trace["claim_axes"] = claims
    trace["claim_components"] = []
    from guardian_truth.vnext.e2e.core_v1 import Component
    for comp in getattr(analysis, "_claims_components", ()) or ():
        pass
    # claims are embedded in problem axes; capture via problem below

    # ledger events + effects
    trace["ledger"] = {
        "event_count": len(analysis.ledger.events),
        "events": [
            {"event_id": e.event_id, "kind": e.kind, "name": getattr(e, "name", None),
             "call_id": getattr(e, "call_id", None),
             "text": (e.text[:220] if getattr(e, "text", None) else None)}
            for e in analysis.ledger.events],
        "effects": [
            {"effect_id": ef.effect_id, "predicate": ef.predicate,
             "value_json": (ef.value_json[:200] if isinstance(ef.value_json, str) else ef.value_json),
             "event_id": ef.event_id, "provenance": ef.provenance,
             "trusted": bool(ef.contract_sha256)}
            for ef in analysis.ledger.effects],
    }

    # problem: axes + worlds + obligations
    trace["axes"] = [
        {"name": ax.name, "choices": list(ax.choice_ids),
         "universe_source": (ax.universe_source or "")[:160],
         "complete": ax.enumeration_complete}
        for ax in analysis.problem.axes]
    trace["world_count"] = analysis.world_count
    trace["required_worlds"] = analysis.required_worlds
    trace["worlds"] = []
    for world in analysis.problem.worlds:
        trace["worlds"].append({
            "world_id": world.world_id,
            "choices": list(world.choices),
            "markers": [m.reason[:200] for m in world.markers],
            "groups": [{"group_id": gr.group_id, "rule_id": gr.rule_id,
                        "must_be_true": gr.must_be_true,
                        "per_call_atoms": [[eid, [str(getattr(a, 'predicate', a)) for a in atoms]]
                                            for eid, atoms in gr.per_call_atoms]}
                       for gr in world.groups],
            "obligations": [serialize_obligation(o) for o in world.obligations],
        })

    # solver result
    trace["solver"] = {
        "status": analysis.result.status.value,
        "world_proofs": [
            {"world_id": p.world_id, "choices": list(p.choices),
             "error_value": p.error_value.value if hasattr(p.error_value, "value") else str(p.error_value),
             "obligation_safety": [[oid, v.value if hasattr(v, "value") else str(v)]
                                   for oid, v in p.obligation_safety]}
            for p in analysis.result.world_proofs],
        "diagnostics": {
            "primary": analysis.result.diagnostics.primary_reason.value
            if analysis.result.diagnostics.primary_reason else None,
            "contributing": [r.value for r in analysis.result.diagnostics.contributing_reasons],
            "missing_evidence": list(analysis.result.diagnostics.missing_evidence),
        },
    }

    # certificate
    cert = analysis.result.certificate
    check = analysis.result.certificate_check
    trace["certificate"] = {
        "present": cert is not None,
        "status": cert.status.value if cert else None,
        "source_sha256": cert.source_sha256 if cert else None,
        "problem_sha256": cert.problem_sha256 if cert else None,
        "check_valid": bool(check.valid) if check else None,
        "check_errors": list(check.errors)[:10] if check else None,
    }

    # frontend failures + summary
    trace["frontend_statuses"] = [
        {"component": c, "kind": k, "detail": (d or "")[:400]}
        for c, k, d in analysis.frontend_statuses]
    trace["component_summary"] = dict(analysis.component_summary)
    trace["product_decision"] = {
        "binary_label": analysis.product_decision.binary_label,
        "used_fallback": analysis.product_decision.used_fallback,
    }
    return {"raw": raw, "trace": trace}


def main():
    import pandas as pd
    frame = pd.read_parquet(REPO_ROOT / "valid.parquet")
    gold = {str(r["id"]): r for _, r in frame.iterrows()}
    fn_list = json.loads((AUDIT_DIR / "fn_list.json").read_text())
    fn_ids = [entry["case_id"] for entry in fn_list["fn"]]

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    backend = build_backend(WORK_CACHE, provider="mistral")

    from real_valid_common import load_firewalled_rows
    rows = {r["id"]: r for r in load_firewalled_rows()}
    for case_id in fn_ids:
        out_path = TRACE_DIR / f"{case_id.replace('/', '_')}.json"
        if out_path.exists():
            print(f"skip {case_id} (trace exists)", flush=True)
            continue
        record = trace_case(backend, rows[case_id], gold[case_id])
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        misses = sum(1 for r in backend.receipts if not r["cache_hit"])
        print(f"traced {case_id} (cumulative live calls: {misses})", flush=True)
    misses = sum(1 for r in backend.receipts if not r["cache_hit"])
    print(f"DONE. live LLM calls during tracing: {misses}")


if __name__ == "__main__":
    main()

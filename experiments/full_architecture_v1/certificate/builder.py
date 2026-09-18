"""full_architecture_v1 — Phase C: source-backed certificate builder (§17).

The Clingo model is NOT the certificate.  This builder reconnects the formal
reasoning (BackendResult from the split evidence/policy program) to the
NeutralCoreInput's source references and fact records, producing a
serializable, hash-chained certificate:

  conclusion + worlds + per-rule witnesses (source spans, bindings,
  event/evidence ids, unknown dependencies, solver conclusion) +
  completeness assumptions + the exact serialized proof facts an
  independent checker needs.

Everything the checker consumes is INSIDE the certificate (plus the
NeutralCoreInput it claims to be about); no LLM, no embedding, no NLI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
if str(_BAKEOFF) not in sys.path:
    sys.path.insert(0, str(_BAKEOFF))

from neutral_types import BackendResult, NeutralCoreInput  # noqa: E402

CERT_SCHEMA_VERSION = "fullarch-certificate/1.0"


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _fact_record(fact) -> dict:
    return {"fact_id": fact.fact_id, "kind": fact.kind, "actor": fact.actor,
            "entity": fact.entity, "predicate": fact.predicate,
            "value": fact.value, "event_index": fact.event_index,
            "call_id": fact.call_id, "region": fact.region,
            "evidence_status": fact.evidence_status,
            "source_ref": fact.source_ref}


def build_certificate(ci: NeutralCoreInput, result: BackendResult,
                      frontend: dict[str, Any] | None = None) -> dict:
    """Build the certificate for one (input, solver result) pair."""
    facts = {f.fact_id: f for f in ci.facts}

    witnesses = []
    for witness in result.witnesses:
        rule_refs = (ci.source_refs.get(witness.rule_id)
                     if isinstance(ci.source_refs, dict) else None)
        spans = rule_refs.get("spans", []) if isinstance(rule_refs, dict) else []
        supporting = [_fact_record(facts[fid]) for fid in witness.supporting_fact_ids
                      if fid in facts]
        refuting = [_fact_record(facts[fid]) for fid in witness.refuting_fact_ids
                    if fid in facts]
        witnesses.append({
            "rule_id": witness.rule_id,
            "interpretation_id": witness.interpretation_id,
            "conclusion": witness.conclusion,
            "source_spans": spans,
            "target_text": (rule_refs or {}).get("target_text", ""),
            "supporting_facts": supporting,
            "refuting_facts": refuting,
            "unknown_dependencies": list(witness.unknown_dependencies),
            "solver_explanation": witness.engine_native_explanation,
        })

    worlds = [{
        "interp_id": w.interp_id,
        "error_value": w.error_value,
        "obligation_safety": [
            {"obligation_id": oid, "safety": value}
            for oid, value in w.obligation_safety],
    } for w in result.worlds]

    body = {
        "schema_version": CERT_SCHEMA_VERSION,
        "case_id": ci.case_id,
        "input_content_hash": ci.content_hash(),
        "backend": result.backend,
        "backend_notes": result.notes,
        "conclusion": result.status,
        "worlds": worlds,
        "witnesses": witnesses,
        "completeness_assumptions": {
            "history_complete": ci.history_complete,
            "completeness_basis": ci.completeness_basis,
            "closed_action_universe": list(ci.closed_action_universe),
            "explicit": True,
        },
        "source_refs": ci.source_refs if isinstance(ci.source_refs, dict) else {},
        "frontend": frontend or {"frontend": "unknown"},
    }
    body["certificate_digest"] = _digest(body)
    return body

"""full_architecture_v1 — Phase C: independent certificate checker (§18).

Deterministic, LLM-free verification of a built certificate:
  C1 digest           — the certificate digest recomputes from the body
  C2 input hash       — the claimed input_content_hash equals the actual
                        NeutralCoreInput content hash
  C3 source refs      — every witness source span exists in source_refs and
                        is well-formed (document/start/end/quote)
  C4 events exist     — every supporting/refuting fact id exists in the input
  C5 evidence match   — serialized fact records match the input's facts
  C6 conclusion       — the conclusion follows from the worlds by the S6/S7
                        consensus algebra recomputed HERE (solver = checker)
  C7 safety algebra   — each world's error value follows from its obligation
                        safety values + interpretation markers (S6)
  C8 completeness     — assumptions are explicit (never silently defaulted)

The checker never imports: Mistral, NuExtract, GLiNER, embeddings, NLI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
if str(_BAKEOFF) not in sys.path:
    sys.path.insert(0, str(_BAKEOFF))

from neutral_types import NeutralCoreInput  # noqa: E402


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def check_certificate(cert: dict, ci: NeutralCoreInput) -> dict:
    """Return {ok: bool, failures: [codes], checks: {...}}."""
    failures: list[str] = []
    checks = {}

    # C1 digest
    body = {k: v for k, v in cert.items() if k != "certificate_digest"}
    recomputed = _digest(body)
    checks["C1_digest"] = recomputed == cert.get("certificate_digest")
    if not checks["C1_digest"]:
        failures.append("C1_DIGEST_MISMATCH")

    # C2 input hash
    checks["C2_input_hash"] = cert.get("input_content_hash") == ci.content_hash()
    if not checks["C2_input_hash"]:
        failures.append("C2_INPUT_HASH_MISMATCH")

    # C3 source refs
    refs = ci.source_refs if isinstance(ci.source_refs, dict) else {}
    span_failures = []
    for witness in cert.get("witnesses", []):
        for span in witness.get("source_spans", []):
            if not isinstance(span, dict) or \
                    not {"document", "start", "end", "quote"} <= set(span):
                span_failures.append(f"malformed:{witness.get('rule_id')}")
                continue
            rule_refs = refs.get(witness.get("rule_id"), {})
            known = any(
                (s.get("start") == span.get("start")
                 and s.get("end") == span.get("end"))
                for s in (rule_refs.get("spans", []) if isinstance(rule_refs, dict)
                          else []))
            if not known:
                span_failures.append(f"unknown-span:{witness.get('rule_id')}"
                                     f"@{span.get('start')}")
    checks["C3_source_refs"] = not span_failures
    failures.extend(span_failures)

    # C4 + C5 events and evidence records
    fact_map = {f.fact_id: f for f in ci.facts}
    event_failures = []
    for witness in cert.get("witnesses", []):
        for key in ("supporting_facts", "refuting_facts"):
            for record in witness.get(key, []):
                fid = record.get("fact_id")
                if fid not in fact_map:
                    event_failures.append(f"missing-fact:{fid}")
                    continue
                fact = fact_map[fid]
                if (record.get("kind") != fact.kind
                        or record.get("predicate") != fact.predicate
                        or record.get("event_index") != fact.event_index
                        or record.get("entity") != fact.entity
                        or record.get("actor") != fact.actor):
                    event_failures.append(f"record-mismatch:{fid}")
    checks["C4_C5_events_evidence"] = not event_failures
    failures.extend(event_failures)

    # C7 world algebra (S6): error value follows from safety values
    # (safety values arrive in the BackendResult truth vocabulary:
    #  TRUE / FALSE / BOTH / UNKNOWN)
    interp_markers = {i.interp_id: tuple(i.unresolved)
                      for i in ci.interpretations}
    algebra_failures = []
    for world in cert.get("worlds", []):
        safeties = [entry["safety"]
                    for entry in world.get("obligation_safety", [])]
        markers = interp_markers.get(world.get("interp_id"), ())
        if "FALSE" in safeties:
            expected = "TRUE"
        elif "BOTH" in safeties:
            expected = "BOTH"
        elif "UNKNOWN" in safeties or markers:
            expected = "UNKNOWN"
        elif safeties:
            expected = "FALSE"
        else:
            expected = "FALSE"
        if world.get("error_value") != expected:
            algebra_failures.append(
                f"world-algebra:{world.get('interp_id')}"
                f":{world.get('error_value')}!={expected}")
    checks["C7_world_algebra"] = not algebra_failures
    failures.extend(algebra_failures)

    # C6 conclusion (S7 consensus) recomputed from worlds
    values = [w.get("error_value") for w in cert.get("worlds", [])]
    if not values:
        expected_status = "UNRESOLVED"
    elif "BOTH" in values:
        expected_status = "INCONSISTENT"
    elif "UNKNOWN" in values:
        expected_status = "UNRESOLVED"
    elif all(v == "TRUE" for v in values):
        expected_status = "PROVED_ERROR"
    elif all(v == "FALSE" for v in values):
        expected_status = "PROVED_NO_ERROR"
    else:
        expected_status = "UNRESOLVED"
    checks["C6_conclusion"] = cert.get("conclusion") == expected_status
    if not checks["C6_conclusion"]:
        failures.append(f"C6_CONCLUSION_MISMATCH:"
                        f"{cert.get('conclusion')}!={expected_status}")

    # C8 completeness assumptions explicit
    assumptions = cert.get("completeness_assumptions", {})
    checks["C8_completeness_explicit"] = (
        isinstance(assumptions, dict)
        and "history_complete" in assumptions
        and assumptions.get("explicit") is True)
    if not checks["C8_completeness_explicit"]:
        failures.append("C8_COMPLETENESS_NOT_EXPLICIT")

    return {"ok": not failures, "failures": failures, "checks": checks}

#!/usr/bin/env python3
"""Adversarial probe: inconsistency-collapse reachability (directive sections 5-6).

Q: can a world whose safety conjuncts are [BOTH, UNKNOWN] (contradictory
trusted evidence + an unresolved conjunct, NO certified FALSE witness)
produce a definitive PROVED_ERROR?

Lattice fact: conjunction([BOTH, UNKNOWN]) = FALSE -> error = TRUE.
If reachable end-to-end, that is UNSOUND_INCONSISTENCY_COLLAPSE (class B):
the ERROR certification rests on the contradiction's negative bit, not on an
independent FALSE safety witness.

Scenarios:
  N1  claim A: BOTH evidence (same-event contradictory verified effects)
      + claim B: UNKNOWN (no evidence)              -> expect NOT PROVED_ERROR
  N2  claim A: BOTH + unbound-claim marker (UNKNOWN) -> expect NOT PROVED_ERROR
  P1  claim A: BOTH + claim B: FALSE (fresh read refutes B)
      -> PROVED_ERROR ALLOWED (independent witness, classification A)
  P2  claim A: BOTH alone                          -> expect INCONSISTENT
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/e2e"))
sys.path.insert(0, str(ROOT / "tests/e2e_soundness"))

from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput  # noqa: E402
from guardian_truth.vnext.e2e.experiment_v1 import registry_for  # noqa: E402
from guardian_truth.vnext.types import Truth  # noqa: E402
from test_e2e_v1_claims import claim_passes, claims_backend  # noqa: E402
from test_e2e_v1_core import ScriptedBackend, goal_frame_desired  # noqa: E402

READER = {"name": "fetch_status", "provider": "bench", "version": "1.0",
          "schema_sha256": "b" * 64}
MUTATOR = {"name": "set_status", "provider": "bench", "version": "1.0",
           "schema_sha256": "c" * 64}


def _call(tool, args, call_id):
    return f'⟦ASSISTANT_TOOL_CALL name="{tool}" call_id="{call_id}"⟧\n{args}'


def _result(tool, payload, call_id):
    return f'⟦TOOL_RESULT name="{tool}" requestor="assistant" call_id="{call_id}"⟧\n{payload}'


def _contract(name, identity, **overrides):
    contract = {"identity": dict(identity or {"name": name, "provider": "bench",
                                              "version": "1.0", "schema_sha256": "c" * 64}),
                "preconditions": [], "reads": [], "writes": [], "guarantees": [],
                "possible_effects": [], "no_effect_conditions": [],
                "failure_semantics": "documented", "freshness": "fresh-read",
                "idempotence": "idempotent", "provenance": "bench_authoritative_contract"}
    contract.update(overrides)
    return contract


CONTRADICTORY_MUTATOR = _contract(
    "set_status", MUTATOR, writes=["status"],
    guarantees=[
        {"conditions": [{"source": "result", "path": ["status"], "equals_json": '"SUCCESS"'}],
         "effects": [{"argument_entity_field": "order_id", "predicate": "status",
                      "value_json": '"cancelled"', "causal_action_confirmed": True}]},
        {"conditions": [{"source": "result", "path": ["status"], "equals_json": '"SUCCESS"'}],
         "effects": [{"argument_entity_field": "order_id", "predicate": "status",
                      "value_json": '"active"', "causal_action_confirmed": True}]}])

READER_CONTRACT = _contract("fetch_status", READER)


def spans_backend(per_span_fields):
    """Claim-extraction backend scripting DIFFERENT claim fields per span."""
    responses = {}

    def _make_handler(task):
        def handler(payload, schema):
            spans = payload["span_inventory"]
            out = []
            for i, span in enumerate(spans):
                fields = per_span_fields[min(i, len(per_span_fields) - 1)]
                out.append({"span_id": span["span_id"], **fields.get(task, {})})
            return {"spans": out}
        return handler
    for task in ("claim_disposition", "claim_kind", "claim_actor", "claim_predicate",
                 "claim_object_entities", "claim_modality_polarity", "claim_time",
                 "claim_source", "claim_explicit_causality"):
        responses[task] = _make_handler(task)
    responses["claim_relations"] = {"relations": []}
    return responses


def merge_fields(*field_dicts):
    merged = {}
    for d in field_dicts:
        merged.update(d)
    return merged


def run(name, history, response_text, contracts, per_span_fields, complete=True):
    case = E2ECaseInput(
        case_id="t-collapse", family="soundness_controlled",
        system_policy="", user_request="Update the status of order ORD-1.",
        history=tuple(history),
        target_response="⟦ASSISTANT⟧\n" + response_text + "\n",
        tool_metadata=(dict(READER), dict(MUTATOR)),
        tool_schemas=({"name": "fetch_status"}, {"name": "set_status"}),
        t1_contracts=tuple(contracts),
        history_complete=complete,
        completeness_basis="controlled complete history" if complete else None,
        gold_core_status="UNRESOLVED", gold_binary=None)
    backend = ScriptedBackend(spans_backend(per_span_fields))
    backend.responses["goal_conservative_frames"] = {
        "frames": [goal_frame_desired("set_status", ["Update the status of order ORD-1."])]}
    guardian = GuardianE2EV1(backend, registry=registry_for(case))
    analysis = guardian.analyze_e2e_v1(case)
    print(f"--- {name}: status={analysis.result.status.value} "
          f"cert={analysis.result.certificate_check.valid if analysis.result.certificate_check else None}")
    for world in analysis.result.world_proofs:
        print(f"    {world.world_id} error={world.error_value.name} safety="
              + ", ".join(f"{oid}={v.name}" for oid, v in world.obligation_safety))
        for prim in world.primitives:
            print(f"      atom {prim.atom.predicate} exp={prim.atom.expected_json} -> {prim.value.name}"
                  f" sup={list(prim.supports)} ref={list(prim.refutes)}")
    return analysis


# ---- N1: BOTH claim + UNKNOWN claim (no FALSE witness) ----
run("N1 BOTH+UNKNOWN_obligation",
    (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
     _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1")),
    "The status of order ORD-1 is cancelled. The priority of order ORD-1 is high.",
    (CONTRADICTORY_MUTATOR,),
    [merge_fields(claim_passes("STATE", "status", "cancelled", ["ORD-1"])),
     merge_fields(claim_passes("STATE", "priority", "high", ["ORD-1"]))])

# ---- N2: BOTH claim + unbound claim marker ----
run("N2 BOTH+UNKNOWN_marker",
    (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
     _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1")),
    "The status of order ORD-1 is cancelled. The priority of order ZZZ-9 is high.",
    (CONTRADICTORY_MUTATOR,),
    [merge_fields(claim_passes("STATE", "status", "cancelled", ["ORD-1"])),
     merge_fields(claim_passes("STATE", "priority", "high", ["ZZZ-9"]))])

# ---- P1: BOTH claim + FALSE claim (independent fresh-read refutation) ----
run("P1 BOTH+FALSE (allowed A)",
    (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
     _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"),
     _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
     _result("fetch_status", '{"order_id": "ORD-1", "status": "active", "priority": "low"}', "c2")),
    "The status of order ORD-1 is cancelled. The priority of order ORD-1 is high.",
    (CONTRADICTORY_MUTATOR, READER_CONTRACT),
    [merge_fields(claim_passes("STATE", "status", "cancelled", ["ORD-1"])),
     merge_fields(claim_passes("STATE", "priority", "high", ["ORD-1"]))])

# ---- P1b: TRUE paired case - BOTH claim (no fresher status evidence) +
#      FALSE claim on a DIFFERENT predicate (fresh read refutes priority) ----
run("P1b BOTH+FALSE_diff_predicate (allowed A)",
    (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
     _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"),
     _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
     _result("fetch_status", '{"order_id": "ORD-1", "priority": "low"}', "c2")),
    "The status of order ORD-1 is cancelled. The priority of order ORD-1 is high.",
    (CONTRADICTORY_MUTATOR, READER_CONTRACT),
    [merge_fields(claim_passes("STATE", "status", "cancelled", ["ORD-1"])),
     merge_fields(claim_passes("STATE", "priority", "high", ["ORD-1"]))])

# ---- P2: BOTH claim alone ----
run("P2 BOTH_alone",
    (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
     _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1")),
    "The status of order ORD-1 is cancelled.",
    (CONTRADICTORY_MUTATOR,),
    [merge_fields(claim_passes("STATE", "status", "cancelled", ["ORD-1"]))])

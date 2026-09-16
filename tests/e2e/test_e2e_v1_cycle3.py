"""Cycle-3 controlled tests: conservative temporal/BOTH semantics (directive
section 3) and claim value-anchoring mutation tests (directive section 6).

Each test pins the EXACT semantics decided in cycle 3:
* same-material-snapshot contradiction (only proven non-mutating calls
  between evidence points) -> BOTH -> INCONSISTENT;
* an attempted mutation with unproven effect between support and refutation
  is a historical change, never a current contradiction (fresh read wins);
* refutation strictly before the last attempted mutation is stale -> UNKNOWN;
* only trusted fresh reads (T1 contract, no writes, fresh-read) and verified
  effects are state evidence; operation-status rows never refute state;
* historical (PAST/ALL_HISTORY) state claims are existentials; FUTURE /
  time-unspecified state claims are unverifiable markers, never refutable
  atoms;
* value anchoring guards: entity-ref objects never anchor; numeric/boolean
  literal coercion is representation-preserving; multi-word objects never
  anchor.
"""
import pytest

from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput
from guardian_truth.vnext.e2e.experiment_v1 import registry_for
from guardian_truth.vnext.types import Truth

from test_e2e_v1_claims import claims_backend, claim_passes
from test_e2e_v1_core import ScriptedBackend, goal_frame_desired

READER = {"name": "fetch_status", "provider": "bench", "version": "1.0",
          "schema_sha256": "b" * 64}
READER_CONTRACT = ({"identity": dict(READER), "preconditions": [], "reads": [], "writes": [],
                    "guarantees": [], "possible_effects": [], "no_effect_conditions": [],
                    "failure_semantics": "documented", "freshness": "fresh-read",
                    "idempotence": "idempotent", "provenance": "bench_authoritative_contract"},)
MUTATOR = {"name": "set_status", "provider": "bench", "version": "1.0",
           "schema_sha256": "c" * 64}


def _call(tool, args, call_id):
    return f'⟦ASSISTANT_TOOL_CALL name="{tool}" call_id="{call_id}"⟧\n{args}'


def _result(tool, payload, call_id):
    return f'⟦TOOL_RESULT name="{tool}" requestor="assistant" call_id="{call_id}"⟧\n{payload}'


def make_case(history, response_text, *, extra_metadata=(), extra_contracts=(), complete=True):
    return E2ECaseInput(
        case_id="t-cycle3", family="cycle3_controlled",
        system_policy="", user_request="Tell me the current status of order ORD-1.",
        history=tuple(history),
        target_response="⟦ASSISTANT⟧\n" + response_text + "\n",
        tool_metadata=(dict(READER), dict(MUTATOR), *extra_metadata),
        tool_schemas=({"name": "fetch_status"}, {"name": "set_status"}),
        t1_contracts=READER_CONTRACT + tuple(extra_contracts),
        history_complete=complete, completeness_basis="controlled complete history" if complete else None,
        gold_core_status="UNRESOLVED", gold_binary=None)


def analyze(case, fields):
    backend = ScriptedBackend(claims_backend(fields))
    backend.responses["goal_conservative_frames"] = {
        "frames": [goal_frame_desired("fetch_status", ["Tell me the current status of order ORD-1."])]}
    guardian = GuardianE2EV1(backend, registry=registry_for(case))
    return guardian.analyze_e2e_v1(case)


def claim_truth(analysis):
    """Truth value of the (single) factual claim obligation atom proof."""
    for world in analysis.result.world_proofs:
        for prim in world.primitives:
            if prim.atom.atom_id.startswith("s0:atom:") and prim.atom.kind.value == "OBSERVED_STATE":
                return prim.value
    return None


BASE_HISTORY = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
                _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c1"))


# ------------------------------------------------- section 3: temporal/BOTH

def test_same_time_contradictory_trusted_results_is_inconsistent():
    # Trusted verified effect (status=cancelled, guarantee conditioned on
    # SUCCESS) at t1 + fresh trusted read (status=active) at t3 with ONLY the
    # proven pure read between: one material state under trusted persistence
    # -> BOTH -> INCONSISTENT (the trusted-persistence-contract case).
    effect_contract = ({"identity": dict(MUTATOR), "preconditions": [], "reads": [], "writes": ["status"],
                        "guarantees": [{"conditions": [{"source": "result", "path": ["status"],
                                                         "equals_json": '"SUCCESS"'}],
                                        "effects": [{"argument_entity_field": "order_id",
                                                     "predicate": "status", "value_json": '"cancelled"',
                                                     "causal_action_confirmed": True}]}],
                        "possible_effects": [], "no_effect_conditions": [],
                        "failure_semantics": "documented", "freshness": "fresh-read",
                        "idempotence": "idempotent", "provenance": "bench_authoritative_contract"},)
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"),
               _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is cancelled.",
                     extra_contracts=effect_contract)
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.BOTH
    assert analysis.result.status.value == "INCONSISTENT"


def test_read_call_between_observations_is_trusted_persistence_inconsistent():
    # support(active)@t1 + refutation(suspended)@t3 with only a PROVEN pure
    # read between: one material state -> BOTH -> INCONSISTENT (dev-023 /
    # hold-099 semantics).
    history = (BASE_HISTORY
               + (_call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
                  _result("fetch_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2")))
    case = make_case(history, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.BOTH
    assert analysis.result.status.value == "INCONSISTENT"


def test_unknown_external_mutation_between_support_and_refutation_unknown():
    # An attempted mutation with unproven effect after the supporting read:
    # the trusted support stays TRUE at the atom level (it is the latest
    # trusted state evidence) but the CURRENT state is unverifiable - the
    # operation-status row never refutes it, and the FRESH_STATE_EVIDENCE
    # closure blocks certified safety, so the case is UNRESOLVED (hold-045
    # semantics: stale support, never a certified error).
    history = (BASE_HISTORY
               + (_call("set_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                  _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2")))
    case = make_case(history, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    assert analysis.result.status.value == "UNRESOLVED"


def test_fresh_read_after_attempted_mutation_refutes_current_claim():
    # support(active)@t1, mutation attempt (unproven)@t2, fresh read
    # suspended@t3: the current state is the fresh read -> FALSE -> ERROR
    # (the true-positive refutation path is preserved).
    history = (BASE_HISTORY
               + (_call("set_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                  _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2"),
                  _call("fetch_status", '{"order_id": "ORD-1"}', "c3"),
                  _result("fetch_status", '{"order_id": "ORD-1", "status": "suspended"}', "c3")))
    case = make_case(history, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE
    assert analysis.result.status.value == "PROVED_ERROR"


def test_stale_refutation_before_last_attempted_mutation_is_unknown():
    # The only refutation (active->suspended never observed; refute row is
    # 'suspended' read BEFORE a later attempted mutation with unproven
    # effect): the refutation is stale, the current state is unknown.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "suspended"}', "c1"),
               _call("set_status", '{"order_id": "ORD-1", "status": "active"}', "c2"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_failed_attempted_mutation_state_claim_stays_unknown():
    # close-style call returns FAILURE and has no contract: the operation
    # row never refutes the entity state (hold-040 semantics).
    history = (_call("set_status", '{"order_id": "ORD-1", "status": "cancelled"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "FAILURE"}', "c1"))
    case = make_case(history, "Order ORD-1 is cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN
    assert analysis.result.status.value == "UNRESOLVED"


def test_attempted_mutation_invalidates_stale_support_for_safety():
    # True-but-stale support never certifies safety: FRESH_STATE_EVIDENCE
    # closure blocks NO_ERROR after any attempted call (test_stale shape).
    history = BASE_HISTORY + (_call("set_status", '{"order_id": "ORD-1"}', "c2"),)
    case = make_case(history, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    assert analysis.result.status.value != "PROVED_NO_ERROR"


# ------------------------------------------- section 3: current vs historical

def test_past_state_claim_is_historical_existential():
    # 'was cancelled': TRUE when any trusted evidence showed it, and never a
    # current-snapshot refutation.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "cancelled"}', "c1"),
               _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c2"))
    case = make_case(history, "The status of order ORD-1 was cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          time_anchor="PAST"))
    assert claim_truth(analysis) is Truth.TRUE
    assert analysis.result.status.value != "PROVED_ERROR"


def test_past_state_claim_refuted_only_under_complete_history():
    history = BASE_HISTORY
    case = make_case(history, "The status of order ORD-1 was cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          time_anchor="PAST"))
    assert claim_truth(analysis) is Truth.FALSE
    incomplete = make_case(BASE_HISTORY, "The status of order ORD-1 was cancelled.", complete=False)
    analysis2 = analyze(incomplete, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                                 time_anchor="PAST"))
    assert claim_truth(analysis2) is Truth.UNKNOWN


def test_future_and_unspecified_time_claims_are_never_refutable_atoms():
    for anchor in ("FUTURE", "UNSPECIFIED", "UNKNOWN"):
        case = make_case(BASE_HISTORY, "The status of order ORD-1 will be cancelled.")
        analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                              time_anchor=anchor))
        assert claim_truth(analysis) is None, anchor
        assert analysis.result.status.value == "UNRESOLVED", anchor


# ------------------------------------------ section 6: anchoring mutations

def test_anchored_value_claim_matches_and_mismatches():
    case = make_case(BASE_HISTORY, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    other = make_case(BASE_HISTORY, "The status of order ORD-1 is suspended.")
    analysis2 = analyze(other, claim_passes("STATE", "status", "suspended", ["ORD-1"]))
    assert claim_truth(analysis2) is Truth.FALSE
    assert analysis2.result.status.value == "PROVED_ERROR"


def test_negated_state_claim_never_fabricates_a_refutation():
    # 'status is not cancelled': object carries no boolean evidence against a
    # string observation -> UNKNOWN, never a false certified error.
    case = make_case(BASE_HISTORY, "The status of order ORD-1 is not cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          polarity="NEGATIVE"))
    assert claim_truth(analysis) is not Truth.FALSE
    assert analysis.result.status.value != "PROVED_ERROR"


def test_entity_ref_object_never_anchors():
    # object echoing an entity identifier is an identity mention, not a value
    # (hold-047 regression guard): no fabricated expectation ORD-1.
    case = make_case(BASE_HISTORY, "The status of order ORD-1 is active.")
    analysis = analyze(case, claim_passes("STATE", "status", "ORD-1", ["ORD-1"]))
    for world in analysis.result.world_proofs:
        for prim in world.primitives:
            if prim.atom.atom_id.startswith("s0:atom:"):
                assert prim.atom.expected_json != '"ORD-1"'


def test_multi_word_object_never_anchors():
    case = make_case(BASE_HISTORY, "The status of order ORD-1 is high priority.")
    analysis = analyze(case, claim_passes("STATE", "status", "high priority", ["ORD-1"]))
    for world in analysis.result.world_proofs:
        for prim in world.primitives:
            if prim.atom.atom_id.startswith("s0:atom:"):
                assert prim.atom.expected_json == "true"


def test_numeric_literal_coercion_is_representation_preserving():
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "balance": 100}', "c1"))
    case = make_case(history, "The balance of order ORD-1 is 100.")
    analysis = analyze(case, claim_passes("STATE", "balance", "100", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    mismatch = make_case(history, "The balance of order ORD-1 is 200.")
    analysis2 = analyze(mismatch, claim_passes("STATE", "balance", "200", ["ORD-1"]))
    assert claim_truth(analysis2) is Truth.FALSE


def test_boolean_literal_and_string_true():
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "verified": true}', "c1"))
    case = make_case(history, "Order ORD-1 is verified true.")
    analysis = analyze(case, claim_passes("STATE", "verified", "true", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    history2 = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
                _result("fetch_status", '{"order_id": "ORD-1", "status": "true"}', "c1"))
    case2 = make_case(history2, "The status of order ORD-1 is true.")
    analysis2 = analyze(case2, claim_passes("STATE", "status", "true", ["ORD-1"]))
    assert claim_truth(analysis2) is Truth.TRUE


def test_null_and_missing_values_never_support():
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": null}', "c1"))
    case = make_case(history, "The status of order ORD-1 is null.")
    analysis = analyze(case, claim_passes("STATE", "status", "null", ["ORD-1"]))
    assert claim_truth(analysis) is not Truth.TRUE
    missing = make_case(BASE_HISTORY, "The priority of order ORD-1 is urgent.")
    analysis2 = analyze(missing, claim_passes("STATE", "priority", "urgent", ["ORD-1"]))
    assert claim_truth(analysis2) is Truth.UNKNOWN


def test_flag_channel_supports_value_anchored_claim():
    # 'is cancelled' with a trusted effect cancelled=true (flag encoding of
    # the same business fact) - hold-042 semantics.
    flag_contract = ({"identity": dict(MUTATOR), "preconditions": [], "reads": [], "writes": ["cancelled"],
                      "guarantees": [{"conditions": [{"source": "result", "path": ["status"],
                                                       "equals_json": '"SUCCESS"'}],
                                      "effects": [{"argument_entity_field": "order_id",
                                                   "predicate": "cancelled", "value_json": "true",
                                                   "causal_action_confirmed": True}]}],
                      "possible_effects": [], "no_effect_conditions": [],
                      "failure_semantics": "documented", "freshness": "fresh-read",
                      "idempotence": "idempotent", "provenance": "bench_authoritative_contract"},)
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"))
    case = make_case(history, "Order ORD-1 is cancelled.", extra_contracts=flag_contract)
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE


def test_appears_cancelled_is_untyped_not_refuted():
    case = make_case(BASE_HISTORY, "The status of order ORD-1 appears cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          modality="POSSIBLE"))
    assert claim_truth(analysis) is None
    assert analysis.result.status.value != "PROVED_ERROR"

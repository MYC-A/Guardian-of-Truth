"""Pre-benchmark soundness micro-suite (audit directive sections 33-35).

Minimal adversarial synthetic cases; each test checks exactly ONE formal
invariant of the B4h proof semantics and states its expected epistemic
result. No benchmark trajectories are reused; no realistic prose beyond
what the claim harness needs. The suite is the machine-checkable form of
docs/vnext/e2e/PRE_BENCHMARK_SOUNDNESS_AUDIT.md (finding IDs referenced as
SND-xx / COV-xx / REP-xx / EMP-xx).

Main invariant under test (directive section 49):
    PROVED means PROVED FROM EXPLICIT TRUSTED PREMISES,
    never 'reasonable under common API conventions'.
"""
import pytest

from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1, extract_behavior_rows
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput
from guardian_truth.vnext.e2e.experiment_v1 import registry_for
from guardian_truth.vnext.types import Truth

from test_e2e_v1_claims import claims_backend, claim_passes
from test_e2e_v1_core import ScriptedBackend, goal_frame_desired

READER = {"name": "fetch_status", "provider": "bench", "version": "1.0",
          "schema_sha256": "b" * 64}
MUTATOR = {"name": "set_status", "provider": "bench", "version": "1.0",
           "schema_sha256": "c" * 64}
EXTRA_TOOLS = ({"name": "fetch_account", "provider": "bench", "version": "1.0",
                "schema_sha256": "d" * 64},)


def _call(tool, args, call_id):
    return f'⟦ASSISTANT_TOOL_CALL name="{tool}" call_id="{call_id}"⟧\n{args}'


def _result(tool, payload, call_id):
    return f'⟦TOOL_RESULT name="{tool}" requestor="assistant" call_id="{call_id}"⟧\n{payload}'


def _reader_contract(name="fetch_status", identity=None, **overrides):
    contract = {"identity": dict(identity or {"name": name, "provider": "bench",
                                               "version": "1.0", "schema_sha256": "b" * 64}),
                "preconditions": [], "reads": [], "writes": [], "guarantees": [],
                "possible_effects": [], "no_effect_conditions": [],
                "failure_semantics": "documented", "freshness": "fresh-read",
                "idempotence": "idempotent", "provenance": "bench_authoritative_contract"}
    contract.update(overrides)
    return contract


def _mutation_contract(predicate="status", value='"cancelled"', identity=None):
    return _reader_contract("set_status", identity or MUTATOR,
                            writes=[predicate],
                            guarantees=[{"conditions": [{"source": "result", "path": ["status"],
                                                         "equals_json": '"SUCCESS"'}],
                                         "effects": [{"argument_entity_field": "order_id",
                                                      "predicate": predicate, "value_json": value,
                                                      "causal_action_confirmed": True}]}])


def make_case(history, response_text, *, contracts=(), metadata=(), schemas=(),
              user_request="Tell me the current status of order ORD-1.", complete=True,
              policy="", authoritative_goal_behaviors=None):
    return E2ECaseInput(
        case_id="t-soundness", family="soundness_controlled",
        system_policy=policy, user_request=user_request,
        history=tuple(history),
        target_response="⟦ASSISTANT⟧\n" + response_text + "\n",
        tool_metadata=(dict(READER), dict(MUTATOR), *metadata),
        tool_schemas=({"name": "fetch_status"}, {"name": "set_status"}, *schemas),
        t1_contracts=tuple(contracts),
        history_complete=complete,
        completeness_basis="controlled complete history" if complete else None,
        authoritative_goal_behaviors=authoritative_goal_behaviors or (),
        gold_core_status="UNRESOLVED", gold_binary=None)


def analyze(case, fields, frames=None):
    backend = ScriptedBackend(claims_backend(fields))
    if frames is None:
        frames = [goal_frame_desired("fetch_status",
                                     ["Tell me the current status of order ORD-1."])]
    backend.responses["goal_conservative_frames"] = {"frames": frames}
    guardian = GuardianE2EV1(backend, registry=registry_for(case))
    return guardian.analyze_e2e_v1(case)


def claim_truth(analysis):
    """Truth value of the (single) factual claim obligation atom proof."""
    for world in analysis.result.world_proofs:
        for prim in world.primitives:
            if prim.atom.atom_id.startswith("s0:atom:") and prim.atom.kind.value == "OBSERVED_STATE":
                return prim.value
    return None


def analyze_with_closure(case, fields, frames=None):
    """Two-pass: author the authoritative goal closure from a first run, then
    re-run so PROVED_NO_ERROR is gated ONLY by the temporal closure premises."""
    first = analyze(case, fields, frames)
    behaviors = extract_behavior_rows(first.goal_lowered)
    closed = E2ECaseInput(**{**case.__dict__,
                             "authoritative_goal_behaviors": behaviors})
    return analyze(closed, fields, frames)


BASE_READ = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
             _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c1"))


# =========================================================================
# AREA A - current-state semantics: persistence, staleness, contradiction
# =========================================================================

def test_A01_external_actor_transition_is_not_contradiction():
    # SND-01 | invariant: cross-time support+refutation is a HISTORICAL pair,
    # never a contradiction without an explicit persistence premise (an
    # external actor may have changed the state between the reads).
    # counterexample: active@t1 -> (external actor blocks) -> blocked@t3, no
    # assistant mutation between. expected: FALSE (freshest trusted read
    # decides the CURRENT claim), never BOTH/INCONSISTENT.
    history = BASE_READ + (_call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
                           _result("fetch_status", '{"order_id": "ORD-1", "status": "blocked"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE
    assert analysis.result.status.value == "PROVED_ERROR"


def test_A02_verified_effect_then_fresh_read_is_not_inconsistent():
    # SND-01 | invariant: a verified trusted effect at t1 and a contradicting
    # trusted fresh read at t3 are historical observations; the CURRENT claim
    # is decided by the freshest trusted evidence. INCONSISTENT would require
    # proving the read wrong, i.e. an unproven persistence premise.
    # (hold-099/dev-023 shape: gold INCONSISTENT under a closed-world
    # assumption the premises never state.)
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"),
               _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is cancelled.",
                     contracts=(_reader_contract(), _mutation_contract()))
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE
    assert analysis.result.status.value == "PROVED_ERROR"


def test_A03_stale_support_before_last_attempted_mutation_is_unknown():
    # SND-02 | invariant: trusted evidence that strictly precedes the LAST
    # attempted mutation (unproven effect) never decides the current state.
    # counterexample: read active@t1; attempted set_status@t2 (no contract,
    # unproven effect); no later read. expected: UNKNOWN, never TRUE.
    history = BASE_READ + (_call("set_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                           _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_A04_stale_support_never_certifies_no_error():
    # SND-02 + SND-08 | invariant (end-to-end): a state claim whose only
    # support precedes an attempted mutation must never yield a certified
    # PROVED_NO_ERROR. The FRESH_STATE_EVIDENCE closure must not be
    # established by the mutation result's own operation-status row.
    # counterexample: read active@t1; set_status@suspended attempted@t2
    # returning {status: SUCCESS}; response claims 'status is active'.
    # expected: UNRESOLVED (was: PROVED_NO_ERROR - false certified safety).
    history = BASE_READ + (_call("set_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                           _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze_with_closure(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert analysis.result.status.value != "PROVED_NO_ERROR"


def test_A05_stale_refutation_with_earlier_support_is_unknown():
    # SND-02 | invariant: staleness is symmetric - a refutation that precedes
    # the last attempted mutation is as indecisive as stale support.
    # counterexample: support active@t1, refute suspended@t2, attempted
    # mutation@t3. expected: UNKNOWN (was: BOTH/FALSE).
    history = BASE_READ + (_call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
                           _result("fetch_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                           _call("set_status", '{"order_id": "ORD-1"}', "c3"),
                           _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c3"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_A06_same_event_contradictory_trusted_effects_is_both():
    # pins sound behavior | invariant: BOTH is justified only for a
    # same-position (single-event snapshot) contradiction - here one trusted
    # result event whose contract emits two contradictory verified effects.
    contract = _reader_contract("set_status", MUTATOR, writes=["status"],
                                guarantees=[
        {"conditions": [{"source": "result", "path": ["status"], "equals_json": '"SUCCESS"'}],
         "effects": [{"argument_entity_field": "order_id", "predicate": "status",
                      "value_json": '"cancelled"', "causal_action_confirmed": True}]},
        {"conditions": [{"source": "result", "path": ["status"], "equals_json": '"SUCCESS"'}],
         "effects": [{"argument_entity_field": "order_id", "predicate": "status",
                      "value_json": '"active"', "causal_action_confirmed": True}]}])
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"))
    case = make_case(history, "The status of order ORD-1 is cancelled.", contracts=(contract,))
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.BOTH


def test_A07_fresh_read_after_mutation_refutes_current_claim():
    # pins sound behavior | invariant: the true-positive refutation path is
    # preserved - a fresh trusted read AFTER the last attempted mutation
    # decides the current claim (freshest evidence wins, not stale).
    history = BASE_READ + (_call("set_status", '{"order_id": "ORD-1", "status": "suspended"}', "c2"),
                           _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c2"),
                           _call("fetch_status", '{"order_id": "ORD-1"}', "c3"),
                           _result("fetch_status", '{"order_id": "ORD-1", "status": "suspended"}', "c3"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE
    assert analysis.result.status.value == "PROVED_ERROR"


def test_A08_latest_read_with_no_later_mutations_proves_claim():
    # pins declared semantics | invariant: OBSERVED_STATE@LATEST means the
    # newest trusted observation with nothing attempted after it - a read
    # that is the last event proves the current claim (declared LATEST
    # semantics; no persistence beyond the evidence is inferred).
    case = make_case(BASE_READ, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE


# =========================================================================
# AREA B - fresh-read semantics: envelopes, field binding, failed reads
# =========================================================================

def test_B01_envelope_row_of_nested_reader_never_refutes():
    # SND-03 | invariant: a pure reader's top-level operation-status field is
    # not an entity-state observation of the nested entity. No T1 binding
    # ties the output path 'status' to the semantic predicate 'status'.
    # counterexample: {status: SUCCESS, account: {id: A-1, status: pending}}.
    # expected: UNKNOWN (the envelope row must not refute 'status is active').
    history = (_call("fetch_account", '{"account_id": "A-1"}', "c1"),
               _result("fetch_account",
                       '{"status": "SUCCESS", "account": {"id": "A-1", "status": "pending"}}', "c1"))
    case = make_case(history, "The status of account A-1 is active.",
                     contracts=(_reader_contract("fetch_account", EXTRA_TOOLS[0]),),
                     metadata=(dict(EXTRA_TOOLS[0]),), schemas=({"name": "fetch_account"},),
                     user_request="Tell me the current status of account A-1.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["A-1"]),
                       frames=[goal_frame_desired("fetch_account",
                                                  ["Tell me the current status of account A-1."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_B02_flat_multi_entity_row_is_not_attributable():
    # SND-03 | invariant: an observation row in a JSON object carrying TWO
    # distinct entity refs is not attributable to either entity (entity
    # binding must be field-level, not event-level).
    # counterexample: {from_account: A-1, to_account: A-2, from_balance: 100}.
    # expected: UNKNOWN for a claim anchored to either entity (was TRUE even
    # for the wrong entity A-2).
    history = (_call("fetch_account", '{"account_id": "A-1"}', "c1"),
               _result("fetch_account",
                       '{"from_account": "A-1", "to_account": "A-2", "from_balance": 100}', "c1"))
    case = make_case(history, "The from_balance of account A-2 is 100.",
                     contracts=(_reader_contract("fetch_account", EXTRA_TOOLS[0]),),
                     metadata=(dict(EXTRA_TOOLS[0]),), schemas=({"name": "fetch_account"},),
                     user_request="Tell me the balances of the accounts.")
    analysis = analyze(case, claim_passes("STATE", "from_balance", "100", ["A-2"]),
                       frames=[goal_frame_desired("fetch_account",
                                                  ["Tell me the balances of the accounts."])])
    # the row is not attributable: either the claim stays unbound (non-_id
    # entity keys bind no entity refs) or the atom proves UNKNOWN - never a
    # definitive support from a row in an object naming two entities.
    assert claim_truth(analysis) in (None, Truth.UNKNOWN)
    assert analysis.result.status.value != "PROVED_NO_ERROR"


def test_B03_reader_with_unrelated_writes_discards_rows():
    # COV-01 (documented coverage limitation) | invariant: a tool that
    # writes anything (even an unrelated audit field) is not a pure reader;
    # its result rows are operation outcomes, never state evidence.
    # expected: UNKNOWN - sound abstention, NOT a soundness bug.
    contract = _reader_contract("fetch_status", READER, writes=["audit.last_access"])
    case = make_case(BASE_READ, "The status of order ORD-1 is active.", contracts=(contract,))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_B04_failed_pure_read_never_refutes_state():
    # SND-05 | invariant: a T1 read is a trusted fresh state observation only
    # when the contract's preconditions held (a failed read did not observe
    # anything; its payload is an error envelope).
    # counterexample: contract preconditions require result.status=SUCCESS;
    # the read returns {status: FAILURE}. expected: UNKNOWN (was: FALSE from
    # the envelope row 'status: FAILURE').
    contract = _reader_contract("fetch_status", READER,
                                preconditions=[{"source": "result", "path": ["status"],
                                                "equals_json": '"SUCCESS"'}])
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status",
                       '{"order_id": "ORD-1", "status": "FAILURE", "error": "timeout"}', "c1"))
    case = make_case(history, "The status of order ORD-1 is active.", contracts=(contract,))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN
    assert analysis.result.status.value != "PROVED_ERROR"


@pytest.mark.xfail(strict=True, reason=(
    "SND-03 residual open risk: a FLAT single-entity envelope "
    "({'request_id','status':'SUCCESS'}) is indistinguishable from a flat "
    "business field in the current representation. The sound fix requires T1 "
    "field-level read contracts (REP-01: output_path/entity_ref/predicate per "
    "read), which cannot be retrofitted to the frozen corpus. Documented in "
    "PRE_BENCHMARK_SOUNDNESS_AUDIT.md; do not 'fix' with value heuristics."))
def test_B05_flat_envelope_row_never_refutes():
    history = (_call("fetch_account", '{"account_id": "A-1"}', "c1"),
               _result("fetch_account",
                       '{"account_id": "A-1", "status": "SUCCESS"}', "c1"))
    case = make_case(history, "The status of account A-1 is active.",
                     contracts=(_reader_contract("fetch_account", EXTRA_TOOLS[0]),),
                     metadata=(dict(EXTRA_TOOLS[0]),), schemas=({"name": "fetch_account"},),
                     user_request="Tell me the current status of account A-1.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["A-1"]),
                       frames=[goal_frame_desired("fetch_account",
                                                  ["Tell me the current status of account A-1."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


# =========================================================================
# AREA C - enum <-> boolean flag equivalence
# =========================================================================

def test_C01_lexical_flag_channel_never_supports():
    # SND-04 | invariant: predicate P == value V is NOT equivalent to
    # predicate V == true unless a trusted source declares the equivalence.
    # counterexample: claim 'color is red' + boolean row {red: true} (an
    # unrelated flag). expected: UNKNOWN (was: TRUE - a false definitive
    # manufactured from the claim's own value token).
    history = (_call("fetch_status", '{"item_id": "ITEM-1"}', "c1"),
               _result("fetch_status", '{"item_id": "ITEM-1", "red": true}', "c1"))
    case = make_case(history, "The color of item ITEM-1 is red.",
                     contracts=(_reader_contract(),),
                     user_request="Tell me the color of item ITEM-1.")
    analysis = analyze(case, claim_passes("STATE", "color", "red", ["ITEM-1"]),
                       frames=[goal_frame_desired("fetch_status",
                                                  ["Tell me the color of item ITEM-1."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_C02_lexical_flag_channel_never_refutes():
    # SND-04 | invariant (refute direction): boolean row {red: false} is not
    # evidence against 'color is red' without a declared equivalence.
    # expected: UNKNOWN (was: FALSE - a false certified ERROR path).
    history = (_call("fetch_status", '{"item_id": "ITEM-1"}', "c1"),
               _result("fetch_status", '{"item_id": "ITEM-1", "red": false}', "c1"))
    case = make_case(history, "The color of item ITEM-1 is red.",
                     contracts=(_reader_contract(),),
                     user_request="Tell me the color of item ITEM-1.")
    analysis = analyze(case, claim_passes("STATE", "color", "red", ["ITEM-1"]),
                       frames=[goal_frame_desired("fetch_status",
                                                  ["Tell me the color of item ITEM-1."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_C03_flag_encoded_field_claim_via_direct_predicate_still_proves():
    # pins preserved behavior | invariant: a claim whose predicate IS the
    # boolean field (object empty -> polarity 'true') is proven by the
    # verified effect on that exact predicate - direct predicate match, no
    # lexical equivalence needed (the hold-042 mechanism that survives).
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"))
    case = make_case(history, "Order ORD-1 is cancelled.",
                     contracts=(_mutation_contract(predicate="cancelled", value="true"),))
    analysis = analyze(case, claim_passes("STATE", "cancelled", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE


# =========================================================================
# AREA D - type coercion
# =========================================================================

def _numeric_case(payload, obj):
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", payload, "c1"))
    case = make_case(history, "The value of order ORD-1 is " + obj + ".",
                     contracts=(_reader_contract(),))
    return claim_truth(analyze(case, claim_passes("STATE", "code", obj, ["ORD-1"])))


def test_D01_string_001_vs_number_1_is_unknown():
    # pins sound behavior | invariant: '001' (string) and 1 (number) are not
    # comparable without a declared canonicalization (leading-zero identity
    # is a semantic distinction, directive section 19).
    assert _numeric_case('{"order_id": "ORD-1", "code": 1}', "001") is Truth.UNKNOWN


def test_D02_string_01234_vs_numeric_is_unknown():
    # pins sound behavior | invariant: postal-style '01234' vs 1234 is not a
    # representation-preserving match; UNKNOWN is the sound result.
    assert _numeric_case('{"order_id": "ORD-1", "code": 1234}', "01234") is Truth.UNKNOWN


def test_D03_canonical_number_encoding_is_comparable():
    # pins declared convention (EMP-01) | invariant: a claim text token that
    # is EXACTLY the canonical JSON encoding of the observed number/boolean
    # is the same value under the adapter's declared canonical-encoding
    # convention (representation repair, audit-recorded). A contract-level
    # canonicalization declaration is the V2 hardening (REP-03).
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "balance": 100}', "c1"))
    case = make_case(history, "The balance of order ORD-1 is 100.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "balance", "100", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE


def test_D04_boolean_literal_convention():
    # pins declared convention | invariant: the adapter's polarity encoding
    # ('true'/'false' strings) canonically denotes JSON booleans; support and
    # mismatch both stay within the declared convention.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "verified": true}', "c1"))
    case = make_case(history, "Order ORD-1 is verified.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "verified", "verified", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.TRUE
    history2 = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
                _result("fetch_status", '{"order_id": "ORD-1", "verified": false}', "c1"))
    case2 = make_case(history2, "Order ORD-1 is verified.",
                      contracts=(_reader_contract(),))
    analysis2 = analyze(case2, claim_passes("STATE", "verified", "verified", ["ORD-1"]))
    assert claim_truth(analysis2) is Truth.FALSE


# =========================================================================
# AREA E - entity binding and output ownership
# =========================================================================

def test_E01_two_entities_one_flat_field_not_attributable():
    # SND-03 | invariant: same predicate name does not mean same entity
    # state (directive 21): a flat row observed in an object naming two
    # entities is unattributable. expected: UNKNOWN for both anchors.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status",
                       '{"a_id": "E-1", "b_id": "E-2", "status": "active"}', "c1"))
    case = make_case(history, "The status of E-1 is active.",
                     contracts=(_reader_contract(),),
                     user_request="Tell me the statuses.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["E-1"]),
                       frames=[goal_frame_desired("fetch_status", ["Tell me the statuses."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_E02_nested_business_field_is_not_bare_predicate():
    # COV-02 (documented coverage limitation) | invariant: a nested business
    # field (account.status) is a different predicate from the bare claim
    # name (status); no false support or refutation crosses the path
    # boundary. expected: UNKNOWN (sound abstention).
    history = (_call("fetch_account", '{"account_id": "A-1"}', "c1"),
               _result("fetch_account",
                       '{"request_id": "R-1", "account": {"id": "A-1", "status": "active"}}', "c1"))
    case = make_case(history, "The status of account A-1 is active.",
                     contracts=(_reader_contract("fetch_account", EXTRA_TOOLS[0]),),
                     metadata=(dict(EXTRA_TOOLS[0]),), schemas=({"name": "fetch_account"},),
                     user_request="Tell me the current status of account A-1.")
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["A-1"]),
                       frames=[goal_frame_desired("fetch_account",
                                                  ["Tell me the current status of account A-1."])])
    assert claim_truth(analysis) is Truth.UNKNOWN


# =========================================================================
# AREA F - failed calls and partial effects
# =========================================================================

def test_F01_failed_uncontracted_mutation_row_never_refutes():
    # pins sound behavior | invariant: FAILED_CALL != NO_EFFECT and its
    # operation-status row is not entity state (hold-040 semantics).
    history = (_call("set_status", '{"order_id": "ORD-1", "status": "cancelled"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "FAILURE"}', "c1"))
    case = make_case(history, "Order ORD-1 is cancelled.")
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_F03_success_conditioned_guarantee_no_effect_on_failure():
    # pins sound behavior | invariant: a guarantee conditioned on
    # result.status=SUCCESS emits no effect when the call failed - the
    # failure status does not fabricate the effect, and partial effects
    # stay exactly what the trusted contract proved.
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "FAILURE"}', "c1"))
    case = make_case(history, "Order ORD-1 is cancelled.",
                     contracts=(_mutation_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_F04_unanswered_call_timeout_still_invalidates_state():
    # pins sound behavior | invariant: a call with NO result (timeout) is an
    # attempted mutation with unproven effect - it never proves absence of
    # effect, and it stales earlier reads. expected: UNKNOWN.
    history = BASE_READ + (_call("set_status", '{"order_id": "ORD-1"}', "c2"),)
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


# =========================================================================
# AREA G - async operations
# =========================================================================

def test_G01_accepted_is_not_completed():
    # pins sound behavior | invariant: lifecycle stages never collapse - a
    # verified effect status='accepted' does not prove 'completed'; distinct
    # literals are distinct values (no invented equivalence).
    history = (_call("set_status", '{"order_id": "ORD-1"}', "c1"),
               _result("set_status", '{"order_id": "ORD-1", "status": "SUCCESS"}', "c1"))
    case = make_case(history, "The export of order ORD-1 is completed.",
                     contracts=(_mutation_contract(predicate="status", value='"accepted"'),))
    analysis = analyze(case, claim_passes("STATE", "status", "completed", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE


# =========================================================================
# AREA H - external actors
# =========================================================================

def test_H02_user_text_between_reads_is_not_a_mutation_premise():
    # SND-01 reinforcement | invariant: an untrusted user text statement
    # between two reads neither proves a state change nor persistence; the
    # freshest trusted read still decides (and no INCONSISTENT is inferred).
    history = BASE_READ + ("⟦USER⟧\nI blocked the order myself.",
                           _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
                           _result("fetch_status", '{"order_id": "ORD-1", "status": "blocked"}', "c2"))
    case = make_case(history, "The status of order ORD-1 is active.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "active", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE
    assert analysis.result.status.value != "INCONSISTENT"


# =========================================================================
# AREA I - complete history vs complete state timeline
# =========================================================================

def test_I01_complete_trace_never_refutes_past_existential():
    # SND-06 | invariant: history_complete certifies the completeness of the
    # SUPPLIED TRACE, not of the entity's state timeline; external mutations
    # never appear as events, so 'was never X' is unprovable.
    # counterexample: complete trace, reads show active; an external actor
    # may have set 'cancelled' between reads. expected: UNKNOWN (was FALSE).
    case = make_case(BASE_READ, "The status of order ORD-1 was cancelled.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          time_anchor="PAST"))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_I02_past_existential_true_via_observation():
    # pins sound behavior | invariant: 'was cancelled' is TRUE when any
    # trusted state evidence in the prefix showed the value (existential).
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "cancelled"}', "c1"),
               _call("fetch_status", '{"order_id": "ORD-1"}', "c2"),
               _result("fetch_status", '{"order_id": "ORD-1", "status": "active"}', "c2"))
    case = make_case(history, "The status of order ORD-1 was cancelled.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          time_anchor="PAST"))
    assert claim_truth(analysis) is Truth.TRUE


def test_I03_incomplete_history_past_existential_unknown():
    # pins sound behavior | invariant: an incomplete prefix can never refute
    # a past state.
    case = make_case(BASE_READ, "The status of order ORD-1 was cancelled.",
                     contracts=(_reader_contract(),), complete=False)
    analysis = analyze(case, claim_passes("STATE", "status", "cancelled", ["ORD-1"],
                                          time_anchor="PAST"))
    assert claim_truth(analysis) is Truth.UNKNOWN


# =========================================================================
# AREA J - NOT_FOUND / absence
# =========================================================================

def test_J01_empty_search_result_proves_nothing():
    # pins sound behavior | invariant: an empty result list is not evidence
    # of absence; no observation row is fabricated from 'no rows'.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"results": []}', "c1"))
    case = make_case(history, "A matching record for ORD-1 exists.",
                     contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "exists", "exists", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.UNKNOWN


def test_J02_trusted_not_found_refutes_exists_claim():
    # pins declared semantics | invariant: a trusted fresh read that RETURNS
    # exists=false does refute 'exists' - the contract vouches the read.
    history = (_call("fetch_status", '{"order_id": "ORD-1"}', "c1"),
               _result("fetch_status", '{"order_id": "ORD-1", "exists": false}', "c1"))
    case = make_case(history, "Order ORD-1 exists.", contracts=(_reader_contract(),))
    analysis = analyze(case, claim_passes("STATE", "exists", "exists", ["ORD-1"]))
    assert claim_truth(analysis) is Truth.FALSE


# =========================================================================
# AREA K - authorization alternatives and cardinality
# =========================================================================

def _binding_dispatcher(mapping):
    """Scripted operational binding: dispatch on hypothesis action key."""
    def handler(payload, schema):
        key = payload["hypothesis"]["action_or_state"]
        entry = mapping.get(key) or mapping.get("*")
        if entry is None:
            return {"candidates": [], "unresolved_terms": ["no binding for " + key]}
        return {"candidates": [{"tool": entry["tool"], "mode": "TARGET_INVOCATION",
                                "checks": entry.get("checks", ()),
                                "covered_clauses": ["action"],
                                "source_quotes": entry["quotes"]}],
                "unresolved_terms": []}
    return handler


def _authorization_frame(alternatives, quote):
    return {"kind": "AUTHORIZATION", "target_level": "ACTION", "content_key": alternatives[0],
            "actor": "UNKNOWN", "scope_entries": [], "conditions": [], "exceptions": [],
            "temporal": "NONE", "coordination": "NONE", "choice": "ANY_OF",
            "alternatives": list(alternatives), "quotes": [quote], "unresolved": []}


def _run_goal_case(user_request, response_call, frames, binding_map, fields):
    history = ()
    case = E2ECaseInput(
        case_id="t-goal", family="soundness_controlled",
        system_policy="", user_request=user_request, history=history,
        target_response="⟦ASSISTANT⟧\nDone.\n" + response_call,
        tool_metadata=({"name": "fetch_status"}, {"name": "set_status"},
                       *( {"name": tool} for tool in binding_map)),
        tool_schemas=({"name": name} for name in ()) or (),
        history_complete=True, completeness_basis="controlled complete history",
        gold_core_status="UNRESOLVED", gold_binary=None)
    backend = ScriptedBackend(claims_backend(fields))
    backend.responses["goal_conservative_frames"] = {"frames": frames}
    backend.responses["operational_action_binding"] = _binding_dispatcher(binding_map)
    guardian = GuardianE2EV1(backend, registry=registry_for(case))
    return guardian.analyze_e2e_v1(case)


def _nonverifiable_claims():
    fields = {"claim_disposition": {"disposition": "NON_VERIFIABLE"}}
    return fields


def test_K01_unlinked_alternatives_do_not_satisfy_requirement():
    # SND-07 | invariant: authorization alternatives of an UNRELATED frame
    # are not satisfaction paths for a requirement (cross-frame
    # authorization is not satisfaction).
    # counterexample: 'Book flight FL-1. Also, cancel hotel H-1 or modify
    # hotel H-1.' + assistant only calls cancel_hotel. expected: PROVED_ERROR
    # (the booking requirement is violated; was satisfiable -> false
    # NO_ERROR path).
    request = "Book flight FL-1 for me. Also, cancel hotel H-1 or modify hotel H-1 as needed."
    response = '⟦ASSISTANT_TOOL_CALL name="cancel_hotel" call_id="t1"⟧\n{"hotel_id": "H-1"}'
    frames = [goal_frame_desired("book_flight", ["Book flight FL-1 for me."]),
              _authorization_frame(["cancel_hotel", "modify_hotel"],
                                   "cancel hotel H-1 or modify hotel H-1 as needed.")]
    binding = {"book_flight": {"tool": "book_flight", "quotes": ["Book flight FL-1 for me."]},
               "cancel_hotel": {"tool": "cancel_hotel", "quotes": ["cancel hotel H-1"]},
               "modify_hotel": {"tool": "modify_hotel", "quotes": ["modify hotel H-1"]}}
    analysis = _run_goal_case(request, response, frames, binding, _nonverifiable_claims())
    assert analysis.result.status.value == "PROVED_ERROR"


def test_K02_linked_alternatives_satisfy_requirement():
    # pins sound behavior (hold-070 shape) | invariant: alternatives declared
    # FOR the requirement (the requirement's action is one of them) remain
    # satisfaction paths - calling the alternative does not violate.
    request = "Check the status of resource RES-1; you can use fetch_resource or lookup_appointment."
    response = '⟦ASSISTANT_TOOL_CALL name="lookup_appointment" call_id="t1"⟧\n{"resource_id": "RES-1"}'
    frames = [goal_frame_desired("fetch_resource",
                                 ["Check the status of resource RES-1;"]),
              _authorization_frame(["fetch_resource", "lookup_appointment"],
                                   "you can use fetch_resource or lookup_appointment.")]
    binding = {"fetch_resource": {"tool": "fetch_resource", "quotes": ["Check the status of resource RES-1;"]},
               "lookup_appointment": {"tool": "lookup_appointment",
                                      "quotes": ["you can use fetch_resource or lookup_appointment."]}}
    analysis = _run_goal_case(request, response, frames, binding, _nonverifiable_claims())
    assert analysis.result.status.value != "PROVED_ERROR"


def test_K03_exactly_one_cardinality_blocks_no_error():
    # pins sound behavior | invariant: EXACTLY_ONE among several alternatives
    # is a real choice cardinality; when it is not expressible the answer is
    # UNRESOLVED (a marker), never a semantic guess (directive 29).
    request = "Close ticket T-1: use close_ticket or resolve_ticket, exactly one of them."
    response = '⟦ASSISTANT_TOOL_CALL name="close_ticket" call_id="t1"⟧\n{"ticket_id": "T-1"}'
    frame = {"kind": "AUTHORIZATION", "target_level": "ACTION", "content_key": "close_ticket",
             "actor": "UNKNOWN", "scope_entries": [], "conditions": [], "exceptions": [],
             "temporal": "NONE", "coordination": "NONE", "choice": "EXACTLY_ONE",
             "alternatives": ["close_ticket", "resolve_ticket"],
             "quotes": ["use close_ticket or resolve_ticket"], "unresolved": []}
    binding = {"close_ticket": {"tool": "close_ticket", "quotes": ["use close_ticket or resolve_ticket"]},
               "resolve_ticket": {"tool": "resolve_ticket",
                                  "quotes": ["use close_ticket or resolve_ticket"]}}
    analysis = _run_goal_case(request, response, [frame], binding, _nonverifiable_claims())
    assert analysis.result.status.value != "PROVED_NO_ERROR"


def test_K04_conditions_on_alternatives_block_no_error():
    # pins sound behavior | invariant: gated alternatives (A OR B with
    # conditions) are not expressible in V1; the marker blocks NO_ERROR
    # instead of guessing the gate semantics.
    request = "Fetch the report; you may use fetch_report or fetch_archive if the user is an admin."
    response = '⟦ASSISTANT_TOOL_CALL name="fetch_report" call_id="t1"⟧\n{"report_id": "R-9"}'
    frame = _authorization_frame(["fetch_report", "fetch_archive"],
                                 "you may use fetch_report or fetch_archive if the user is an admin.")
    frame["conditions"] = ["the user is an admin"]
    binding = {"fetch_report": {"tool": "fetch_report",
                                "quotes": ["you may use fetch_report or fetch_archive if the user is an admin."]},
               "fetch_archive": {"tool": "fetch_archive",
                                 "quotes": ["you may use fetch_report or fetch_archive if the user is an admin."]}}
    analysis = _run_goal_case(request, response, [frame], binding, _nonverifiable_claims())
    assert analysis.result.status.value != "PROVED_NO_ERROR"


# =========================================================================
# AREA M - action prerequisites vs state observations (B0-shared fallback)
# =========================================================================

def test_M01_action_prerequisite_not_resolved_by_operation_row():
    # SND-09 | invariant: the deterministic action-atom observation fallback
    # resolves a gate ONLY from trusted state evidence; an uncontracted
    # mutation result's row (booking: false) never refutes the prerequisite
    # 'check_booking was attempted'. expected: UNKNOWN (was: FALSE).
    from guardian_truth.vnext.e2e.world_integration_v1 import _prove_deterministic_action_atom
    from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
    from guardian_truth.vnext.normalize import normalize
    from guardian_truth.vnext.proof_records import AtomKind, ProofAtom, TimeMode
    from guardian_truth.vnext.types import EntityRef
    from guardian_truth.vnext.tools import ContractRegistry

    prompt = ""
    response = ('⟦ASSISTANT_TOOL_CALL name="set_status" call_id="c1"⟧\n{"order_id": "ORD-1"}\n'
                '⟦TOOL_RESULT name="set_status" requestor="assistant" call_id="c1"⟧\n'
                '{"order_id": "ORD-1", "booking": false}')
    events = normalize(prompt, response, tool_identities=())
    # incomplete history: the sound absence proof for CALL_ATTEMPTED atoms is
    # unavailable, so after excluding the uncontracted operation row the
    # prerequisite must stay UNKNOWN (old code: FALSE from the operation row).
    ledger = EvidenceLedger.from_events(events, history_complete=False)
    index = LedgerIndex(ledger)
    atom = ProofAtom("a1", AtomKind.CALL_ATTEMPTED, EntityRef("prerequisite", "ORD-1", "e2e"),
                     "check_booking", "true", "assistant", TimeMode.THROUGH, 1)
    proof = _prove_deterministic_action_atom(atom, ledger, index, ContractRegistry(()))
    assert proof.value is Truth.UNKNOWN


def test_M02_gate_resolves_from_trusted_reader_row():
    # pins sound behavior (SND-09 companion) | invariant: a gate DOES resolve
    # from a trusted pure-reader boolean row when the predicate matches - the
    # restriction removes untrusted evidence, not the trusted channel.
    from guardian_truth.vnext.e2e.world_integration_v1 import _prove_deterministic_action_atom
    from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
    from guardian_truth.vnext.normalize import normalize
    from guardian_truth.vnext.proof_records import AtomKind, ProofAtom, TimeMode
    from guardian_truth.vnext.types import EntityRef, ToolIdentity
    from guardian_truth.vnext.tools import ContractRegistry, TrustedContract

    reader = ToolIdentity("fetch_status", "bench", "1.0", "b" * 64)
    response = ('⟦ASSISTANT_TOOL_CALL name="fetch_status" call_id="c1"⟧\n{"order_id": "ORD-1"}\n'
                '⟦TOOL_RESULT name="fetch_status" requestor="assistant" call_id="c1"⟧\n'
                '{"order_id": "ORD-1", "booking": true}')
    events = normalize("", response, tool_identities=(reader,))
    ledger = EvidenceLedger.from_events(events, history_complete=True,
                                        completeness_basis="controlled complete history")
    index = LedgerIndex(ledger)
    contract = TrustedContract(reader, (), (), (), (), (), (), "documented",
                               "fresh-read", "idempotent", "bench_authoritative_contract")
    registry = ContractRegistry((contract,))
    atom = ProofAtom("a1", AtomKind.CALL_ATTEMPTED, EntityRef("prerequisite", "ORD-1", "e2e"),
                     "booking", "true", "assistant", TimeMode.THROUGH, 1)
    proof = _prove_deterministic_action_atom(atom, ledger, index, registry)
    assert proof.value is Truth.TRUE

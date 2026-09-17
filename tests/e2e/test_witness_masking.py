"""FALSE-witness masking fix — metamorphic tests.

Invariant under repair (world_integration_v1, spec 96/100):
    "A certified FALSE safety witness in a world makes that world ERROR even
     when unrelated obligations are UNKNOWN - an independent proved violation
     is never masked by unrelated uncertainty."

The fix extends that invariant from unknown CONJUNCTS to un-enumerated
READINGS: when an enumeration-complete axis carries a certified FALSE witness
in every option, the ERROR verdict is invariant under any completion of the
world space, so a failed frontend's incomplete axis cannot mask a proved
violation — neither at the all-world consensus (solve_e2e) nor at the
independent certificate checker (check_e2e_certificate).

Required metamorphic shapes (fix directive):
1. FALSE only                         -> ERROR
2. FALSE + unrelated UNKNOWN          -> ERROR   (the reported bug)
3. FALSE + N unrelated UNKNOWN        -> ERROR
4. UNKNOWN only                       -> UNRESOLVED
5. TRUE + UNKNOWN                     -> UNRESOLVED
6. no FALSE witness                   -> never manufacture ERROR

Soundness counter-shapes (the relaxation must NOT fire):
7. FALSE witness only on an INCOMPLETE axis -> UNRESOLVED (a missing reading
   might not contain the violation);
8. checker independence: a forced PROVED_ERROR certificate without the
   completion-invariant witness is rejected (COMPLETENESS_UNPROVED).

All tests are deterministic and LLM-free (offline backend / direct
composition); nothing depends on valid.parquet.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.certificates import AuthoritativeAxis, CertificateContext
from guardian_truth.vnext.e2e.catalog_conformance_v1 import catalog_conformance_component
from guardian_truth.vnext.e2e.certificate_context_v1 import (E2EBundle, check_e2e_certificate,
                                                             make_e2e_certificate)
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import (E2EArmConfig, E2ECaseInput, ReadingOption,
                                                   SEMANTICS_ARMS, UnresolvedMarker)
from guardian_truth.vnext.e2e.world_integration_v1 import (Component, build_worlds,
                                                           error_witness_completion_invariant,
                                                           make_problem, solve_e2e, solve_world)
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.proof_records import InterpretationAxis
from guardian_truth.vnext.tools import ContractRegistry
from guardian_truth.vnext.types import CoreStatus, Truth

SCHEMAS = {
    "get_user_details": {
        "name": "get_user_details",
        "description": "Get user details.",
        "parameters": {"user_id": {"type": "string", "required": True, "description": ""}},
    },
    "check_line": {
        "name": "check_line",
        "description": "Check line status.",
        "parameters": {"line_id": {"type": "string", "required": True, "description": ""}},
    },
}

VIOLATING_CALL = '→ TOOL_CALL check_network_status: {"line_id": "L1002"}'
CONFORMING_CALL = '→ TOOL_CALL get_user_details: {"user_id": "u1"}'
BOTH_CALLS = VIOLATING_CALL + "\n" + CONFORMING_CALL


# --------------------------------------------------------------- fixtures

def _fixture(response: str):
    """Ledger + registry + per-call catalog obligations of the response."""
    events = normalize("", response)
    ledger = EvidenceLedger.from_events(events, history_complete=True,
                                        completeness_basis="metamorphic fixture")
    registry = ContractRegistry((), schemas=SCHEMAS)
    calls = [event for event in events if event.kind == "call"]
    component = catalog_conformance_component(calls, SCHEMAS)
    assert component is not None, "fixture: response must contain assistant calls"
    all_obligations = next(iter(component.options.values())).obligations
    by_event = {event.event_id: tuple(obligation for obligation in all_obligations
                                      if obligation.obligation_id.startswith(f"catalog:{event.event_id}:"))
                for event in calls}
    return ledger, registry, calls, by_event


def _catalog_option(option_id: str, obligations) -> ReadingOption:
    return ReadingOption(option_id, tuple(obligations), (), ())


def _marker_option(option_id: str) -> ReadingOption:
    return ReadingOption(option_id, (), (), (UnresolvedMarker(option_id, "synthetic unrelated unknown"),))


def _contract(option: ReadingOption) -> dict:
    return {"rules": {"catalog:conformance":
                      {"obligations": tuple(o.obligation_id for o in option.obligations)}},
            "claim_obligations": []}


def _compose(components, ledger, registry, contracts):
    worlds, _required, exceeded = build_worlds(tuple(components), max_worlds=512)
    assert not exceeded
    problem = make_problem(tuple(components), worlds)
    result = solve_e2e(problem, ledger, registry, option_contracts=contracts)
    proofs = [solve_world(world, ledger, LedgerIndex(ledger), registry)
              for world in problem.worlds]
    return problem, result, proofs


def _authority(axis: InterpretationAxis) -> AuthoritativeAxis:
    return AuthoritativeAxis(axis.name, axis.choice_ids,
                             axis.universe_source or "unresolved",
                             "EXPLICIT_SOURCE_IDENTITY" if axis.enumeration_complete
                             else "EMPIRICAL_CANDIDATE_SET")


def _checked_bundle(problem, contracts, ledger, registry, response: str):
    context = CertificateContext("", response, (), (),
                                 tuple(_authority(axis) for axis in problem.axes))
    bundle = E2EBundle(context, problem, contracts, {}, {},
                       {"supplied": True}, {"supplied": True},
                       (("goal_conservative", "TRANSPORT", "metamorphic fixture"),))
    certificate = make_e2e_certificate(CoreStatus.PROVED_ERROR, bundle, ledger, registry)
    assert certificate is not None
    return check_e2e_certificate(certificate, bundle, ledger, registry)


# ---------------------------------------------- shapes 1-3: FALSE -> ERROR

def test_shape_1_false_only_is_error():
    ledger, registry, calls, by_event = _fixture(VIOLATING_CALL)
    witness = Component(
        InterpretationAxis("catalog_conformance", ("catalog_conformance:deterministic",),
                           "explicit prompt tool catalog + typed schemas", True),
        {"catalog_conformance:deterministic": _catalog_option(
            "catalog_conformance:deterministic", by_event[calls[0].event_id])})
    option = next(iter(witness.options.values()))
    problem, result, proofs = _compose([witness], ledger, registry,
                                       {"catalog_conformance:deterministic": _contract(option)})
    assert all(proof.error_value is Truth.TRUE for proof in proofs)
    assert result.status is CoreStatus.PROVED_ERROR


def test_shape_2_false_plus_unrelated_unknown_is_error():
    """THE reported bug: catalog FALSE witness + goal-frontend UNKNOWN marker
    axis (incomplete) must still certify PROVED_ERROR, at the solver AND at
    the independent certificate checker."""
    ledger, registry, calls, by_event = _fixture(VIOLATING_CALL)
    goal = Component(InterpretationAxis("goal", ("goal:unresolved",), None, False),
                     {"goal:unresolved": _marker_option("goal:unresolved")})
    witness = Component(
        InterpretationAxis("catalog_conformance", ("catalog_conformance:deterministic",),
                           "explicit prompt tool catalog + typed schemas", True),
        {"catalog_conformance:deterministic": _catalog_option(
            "catalog_conformance:deterministic", by_event[calls[0].event_id])})
    option = next(iter(witness.options.values()))
    contracts = {"goal:unresolved": {"rules": {}},
                 "catalog_conformance:deterministic": _contract(option)}
    problem, result, proofs = _compose([goal, witness], ledger, registry, contracts)
    # every world: FALSE witness present, UNKNOWN conjuncts dominated
    for proof in proofs:
        assert any(value is Truth.FALSE for _, value in proof.obligation_safety)
        assert any(value is Truth.UNKNOWN for _, value in proof.obligation_safety)
        assert proof.error_value is Truth.TRUE
    assert error_witness_completion_invariant(problem, contracts, ledger, registry)
    assert result.status is CoreStatus.PROVED_ERROR
    assert _checked_bundle(problem, contracts, ledger, registry, VIOLATING_CALL).valid


def test_shape_3_false_plus_n_unrelated_unknowns_is_error():
    """N unrelated UNKNOWN axes (complete-marker and incomplete-marker,
    single- and multi-option) never mask the witness."""
    ledger, registry, calls, by_event = _fixture(VIOLATING_CALL)
    marker_a = Component(InterpretationAxis("axis_a", ("axis_a:m",), "synthetic complete", True),
                         {"axis_a:m": _marker_option("axis_a:m")})
    marker_b = Component(InterpretationAxis("axis_b", ("axis_b:0", "axis_b:1"), "synthetic complete", True),
                         {"axis_b:0": _marker_option("axis_b:0"),
                          "axis_b:1": _marker_option("axis_b:1")})
    marker_c = Component(InterpretationAxis("axis_c", ("axis_c:0", "axis_c:1"), None, False),
                         {"axis_c:0": _marker_option("axis_c:0"),
                          "axis_c:1": _marker_option("axis_c:1")})
    marker_d = Component(InterpretationAxis("axis_d", ("axis_d:m",), None, False),
                         {"axis_d:m": _marker_option("axis_d:m")})
    witness = Component(
        InterpretationAxis("catalog_conformance", ("catalog_conformance:deterministic",),
                           "explicit prompt tool catalog + typed schemas", True),
        {"catalog_conformance:deterministic": _catalog_option(
            "catalog_conformance:deterministic", by_event[calls[0].event_id])})
    option = next(iter(witness.options.values()))
    contracts = {"axis_a:m": {"rules": {}}, "axis_b:0": {"rules": {}}, "axis_b:1": {"rules": {}},
                 "axis_c:0": {"rules": {}}, "axis_c:1": {"rules": {}}, "axis_d:m": {"rules": {}},
                 "catalog_conformance:deterministic": _contract(option)}
    problem, result, proofs = _compose([marker_a, marker_b, marker_c, marker_d, witness],
                                       ledger, registry, contracts)
    assert len(proofs) == 4
    for proof in proofs:
        assert any(value is Truth.FALSE for _, value in proof.obligation_safety)
        assert sum(1 for _, value in proof.obligation_safety if value is Truth.UNKNOWN) >= 3
        assert proof.error_value is Truth.TRUE
    assert result.status is CoreStatus.PROVED_ERROR


# ------------------------------------- shapes 4-5: UNKNOWN never ERROR

def test_shape_4_unknown_only_is_unresolved():
    ledger, registry, calls, by_event = _fixture(VIOLATING_CALL)
    goal = Component(InterpretationAxis("goal", ("goal:unresolved",), None, False),
                     {"goal:unresolved": _marker_option("goal:unresolved")})
    other = Component(InterpretationAxis("axis_a", ("axis_a:m",), "synthetic complete", True),
                      {"axis_a:m": _marker_option("axis_a:m")})
    contracts = {"goal:unresolved": {"rules": {}}, "axis_a:m": {"rules": {}}}
    problem, result, proofs = _compose([goal, other], ledger, registry, contracts)
    for proof in proofs:
        assert proof.error_value is Truth.UNKNOWN
        assert not any(value is Truth.FALSE for _, value in proof.obligation_safety)
    assert not error_witness_completion_invariant(problem, contracts, ledger, registry)
    assert result.status is CoreStatus.UNRESOLVED


def test_shape_5_true_plus_unknown_worlds_is_unresolved():
    """A complete 2-option axis where only ONE option carries the FALSE
    witness: world errors are TRUE + UNKNOWN -> UNRESOLVED (the witness is
    reading-dependent, so PROVED_ERROR would be unsound)."""
    ledger, registry, calls, by_event = _fixture(BOTH_CALLS)
    assert len(calls) == 2
    violating, conforming = by_event[calls[0].event_id], by_event[calls[1].event_id]
    reader = Component(
        InterpretationAxis("reading", ("reading:violating", "reading:clean"),
                           "synthetic complete", True),
        {"reading:violating": _catalog_option("reading:violating", violating),
         "reading:clean": _catalog_option("reading:clean", conforming)})
    marker = Component(InterpretationAxis("axis_a", ("axis_a:m",), "synthetic complete", True),
                       {"axis_a:m": _marker_option("axis_a:m")})
    contracts = {"reading:violating": _contract(reader.options["reading:violating"]),
                 "reading:clean": _contract(reader.options["reading:clean"]),
                 "axis_a:m": {"rules": {}}}
    problem, result, proofs = _compose([reader, marker], ledger, registry, contracts)
    assert sorted(proof.error_value.name for proof in proofs) == ["TRUE", "UNKNOWN"]
    assert not error_witness_completion_invariant(problem, contracts, ledger, registry)
    assert result.status is CoreStatus.UNRESOLVED
    # the incomplete-space variant must stay UNRESOLVED too
    marker_incomplete = Component(InterpretationAxis("axis_a", ("axis_a:m",), None, False),
                                  {"axis_a:m": _marker_option("axis_a:m")})
    problem2, result2, _ = _compose([reader, marker_incomplete], ledger, registry, contracts)
    assert result2.status is CoreStatus.UNRESOLVED
    assert not error_witness_completion_invariant(problem2, contracts, ledger, registry)


# ----------------------- shape 6 + counter-shapes: never manufacture ERROR

def test_shape_6_no_false_witness_never_manufactures_error():
    ledger, registry, calls, by_event = _fixture(CONFORMING_CALL)
    conforming = _catalog_option("catalog_conformance:deterministic",
                                 by_event[calls[0].event_id])
    witness = Component(
        InterpretationAxis("catalog_conformance", ("catalog_conformance:deterministic",),
                           "explicit prompt tool catalog + typed schemas", True),
        {"catalog_conformance:deterministic": conforming})
    contracts = {"catalog_conformance:deterministic": _contract(conforming)}
    # (a) clean complete space: all safety TRUE -> PROVED_NO_ERROR, never ERROR
    problem, result, proofs = _compose([witness], ledger, registry, contracts)
    assert all(proof.error_value is Truth.FALSE for proof in proofs)
    assert result.status is CoreStatus.PROVED_NO_ERROR
    # (b) clean call + unrelated UNKNOWN marker: UNKNOWN, never ERROR
    goal = Component(InterpretationAxis("goal", ("goal:unresolved",), None, False),
                     {"goal:unresolved": _marker_option("goal:unresolved")})
    contracts["goal:unresolved"] = {"rules": {}}
    problem2, result2, proofs2 = _compose([goal, witness], ledger, registry, contracts)
    assert all(proof.error_value is Truth.UNKNOWN for proof in proofs2)
    assert not error_witness_completion_invariant(problem2, contracts, ledger, registry)
    assert result2.status is CoreStatus.UNRESOLVED


def test_counter_witness_only_on_incomplete_axis_stays_unresolved():
    """Soundness counter-shape: the FALSE witness is carried ONLY by the
    option of an INCOMPLETE axis. Every enumerated world is TRUE, but a
    missing reading might not contain the violation, so the verdict must
    stay UNRESOLVED and the forced certificate must be REJECTED."""
    ledger, registry, calls, by_event = _fixture(VIOLATING_CALL)
    broken = Component(InterpretationAxis("broken_frontend", ("broken_frontend:only",), None, False),
                       {"broken_frontend:only": _catalog_option(
                           "broken_frontend:only", by_event[calls[0].event_id])})
    marker = Component(InterpretationAxis("axis_a", ("axis_a:m",), "synthetic complete", True),
                       {"axis_a:m": _marker_option("axis_a:m")})
    contracts = {"broken_frontend:only": _contract(broken.options["broken_frontend:only"]),
                 "axis_a:m": {"rules": {}}}
    problem, result, proofs = _compose([broken, marker], ledger, registry, contracts)
    for proof in proofs:
        assert proof.error_value is Truth.TRUE          # the enumerated world IS error
    assert not error_witness_completion_invariant(problem, contracts, ledger, registry)
    assert result.status is CoreStatus.UNRESOLVED       # ...but not completion-invariant
    check = _checked_bundle(problem, contracts, ledger, registry, VIOLATING_CALL)
    assert not check.valid and "COMPLETENESS_UNPROVED" in check.errors


def test_checker_still_rejects_without_witness_when_space_incomplete():
    """Checker independence on shape 4: UNKNOWN-only composition, forced
    PROVED_ERROR certificate -> COMPLETENESS_UNPROVED (never certified)."""
    ledger, registry, calls, by_event = _fixture(CONFORMING_CALL)
    conforming = _catalog_option("catalog_conformance:deterministic",
                                 by_event[calls[0].event_id])
    goal = Component(InterpretationAxis("goal", ("goal:unresolved",), None, False),
                     {"goal:unresolved": _marker_option("goal:unresolved")})
    witness = Component(
        InterpretationAxis("catalog_conformance", ("catalog_conformance:deterministic",),
                           "explicit prompt tool catalog + typed schemas", True),
        {"catalog_conformance:deterministic": conforming})
    contracts = {"goal:unresolved": {"rules": {}},
                 "catalog_conformance:deterministic": _contract(conforming)}
    problem, result, _ = _compose([goal, witness], ledger, registry, contracts)
    assert result.status is CoreStatus.UNRESOLVED
    check = _checked_bundle(problem, contracts, ledger, registry, CONFORMING_CALL)
    assert not check.valid and "COMPLETENESS_UNPROVED" in check.errors


# ------------------------------------------------- E2E pipeline level

class _OfflineBackend:
    """No live LLM: every semantic proposal fails at the transport level."""

    def propose(self, task, payload, schema):
        from guardian_truth.vnext.semantic import Proposal
        return Proposal(None, "ERROR", "NOT_EVALUATED", "offline_test")


def _guardian():
    return GuardianE2EV1(
        _OfflineBackend(), registry=ContractRegistry((), schemas=SCHEMAS),
        arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
        adapter_mode=AdapterMode.COMPETITION,
        enable_t2=False, semantics=SEMANTICS_ARMS["B3"], catalog_conformance=True)


def _case(response: str) -> E2ECaseInput:
    return E2ECaseInput(
        case_id="t-witness-masking", family="",
        system_policy="",
        user_request="Please check my network status.",
        history=(),
        target_response=response,
    )


def test_e2e_false_witness_with_failed_goal_frontend_is_certified_error():
    """Full pipeline, the minimized telecom-t7 shape: catalog violation in
    the RESPONSE + goal frontend transport failure (incomplete goal axis
    with an UNKNOWN marker) -> PROVED_ERROR with a VALID certificate."""
    analysis = _guardian().analyze_e2e_v1(_case(VIOLATING_CALL))
    axes = {axis.name: axis.enumeration_complete for axis in analysis.problem.axes}
    assert axes == {"policy": True, "goal": False, "catalog_conformance": True}
    assert [proof.error_value for proof in analysis.result.world_proofs] == [Truth.TRUE]
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.result.certificate_check is not None
    assert analysis.result.certificate_check.valid
    assert analysis.product_decision.binary_label == 1
    assert analysis.product_decision.used_fallback is False


def test_e2e_clean_call_with_failed_goal_frontend_never_manufactures_error():
    """Paired clean case: conforming call + the SAME failed goal frontend ->
    no manufactured ERROR (no false-certified verdict)."""
    analysis = _guardian().analyze_e2e_v1(_case(CONFORMING_CALL))
    assert analysis.result.status.value != "PROVED_ERROR"
    assert analysis.product_decision.binary_label != 1


def test_e2e_no_user_request_keeps_prior_certified_behavior():
    """Regression guard: without the failing frontend (no user request at
    all) the pre-fix certified violation path is unchanged."""
    case = E2ECaseInput(case_id="t-witness-masking", family="", system_policy="",
                        user_request="", history=(), target_response=VIOLATING_CALL)
    analysis = _guardian().analyze_e2e_v1(case)
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.result.certificate_check.valid

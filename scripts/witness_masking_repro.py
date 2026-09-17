"""Minimal synthetic reproduction of the FALSE-witness masking bug (independent
of valid.parquet; zero LLM calls; fully deterministic).

Reported invariant (world_integration_v1 module docstring, spec 96/100):
    "A certified FALSE safety witness in a world makes that world ERROR even
     when unrelated obligations are UNKNOWN - an independent proved violation
     is never masked by unrelated uncertainty."

Reproducible failure (the telecom t7 shape, minimized):
    the catalog axis independently proves FALSE (a RESPONSE call to a tool
    absent from the supplied catalog), but an UNRELATED incomplete axis (the
    goal axis a failed goal frontend leaves as `goal:unresolved`) turns the
    FINAL result into UNRESOLVED.

Two independent masking layers are demonstrated:
  L1  all-world consensus: solve_e2e -> consensus(material_space_complete=
      world_space_complete(...)) returns UNRESOLVED even though EVERY world's
      error value is TRUE (the per-world invariant itself holds).
  L2  certificate checking: even with a forced PROVED_ERROR status,
      check_e2e_certificate rejects with COMPLETENESS_UNPROVED because
      SEMANTIC_CANDIDATES_COVERED excludes the incomplete goal axis.

Run:  python scripts/witness_masking_repro.py
Exit code 0 = invariant HOLDS (post-fix), 1 = invariant VIOLATED (pre-fix).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.certificates import AuthoritativeAxis, CertificateContext
from guardian_truth.vnext.e2e.catalog_conformance_v1 import (catalog_conformance_component,
                                                             catalog_option_contract)
from guardian_truth.vnext.e2e.certificate_context_v1 import (E2EBundle, check_e2e_certificate,
                                                             make_e2e_certificate)
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import (E2EArmConfig, E2ECaseInput, FULL_SEMANTICS,
                                                   ReadingOption, SEMANTICS_ARMS, UnresolvedMarker)
from guardian_truth.vnext.e2e.world_integration_v1 import (Component, build_worlds, make_problem,
                                                           solve_e2e, solve_world)
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

RESPONSE = '→ TOOL_CALL check_network_status: {"line_id": "L1002"}'
USER_REQUEST = "Please check my network status."


class _OfflineBackend:
    """No live LLM: every semantic proposal fails at the transport level."""

    def propose(self, task, payload, schema):
        from guardian_truth.vnext.semantic import Proposal
        return Proposal(None, "ERROR", "NOT_EVALUATED", "offline_repro")


def _guardian(schemas):
    return GuardianE2EV1(
        _OfflineBackend(), registry=ContractRegistry((), schemas=schemas),
        arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
        adapter_mode=AdapterMode.COMPETITION,
        enable_t2=False, semantics=SEMANTICS_ARMS["B3"], catalog_conformance=True)


def composition_layer_repro() -> dict:
    """L1 + L2 at the exact composition level: real catalog component over a
    synthetic RESPONSE call + the `goal:unresolved` marker axis a failed goal
    frontend produces."""
    events = normalize("", RESPONSE)
    ledger = EvidenceLedger.from_events(events, history_complete=True,
                                        completeness_basis="synthetic repro")
    registry = ContractRegistry((), schemas=SCHEMAS)
    index = LedgerIndex(ledger)
    calls = [event for event in events if event.kind == "call"]
    catalog = catalog_conformance_component(calls, SCHEMAS)
    assert catalog is not None, "repro fixture: catalog component must activate"

    # The unrelated UNKNOWN: the degenerate fallback option of a goal axis
    # whose frontend failed (core_v1._goal_contracts -> no options). Its
    # enumeration is INCOMPLETE (universe_source None, complete False).
    marker = ReadingOption("goal:unresolved", (), (),
                           (UnresolvedMarker("goal:unresolved", "no goal contract available"),))
    goal = Component(InterpretationAxis("goal", ("goal:unresolved",), None, False),
                     {"goal:unresolved": marker})

    components = (goal, catalog)
    worlds, required, exceeded = build_worlds(components, max_worlds=64)
    problem = make_problem(components, worlds)
    # exactly as core_v1 wires it: one contract per option id
    option_contracts = {"goal:unresolved": {"rules": {}}}
    for choice_id in catalog.options:
        option_contracts[choice_id] = catalog_option_contract(catalog)

    world_lines = []
    for world in problem.worlds:
        proof = solve_world(world, ledger, index, registry, FULL_SEMANTICS)
        false_witnesses = [oid for oid, value in proof.obligation_safety if value is Truth.FALSE]
        unknown_conjuncts = [oid for oid, value in proof.obligation_safety
                             if value is Truth.UNKNOWN]
        world_lines.append({
            "world": world.world_id, "choices": list(world.choices),
            "error_value": proof.error_value.name,
            "false_witnesses": false_witnesses, "unknown_conjuncts": unknown_conjuncts,
        })

    result = solve_e2e(problem, ledger, registry, option_contracts=option_contracts)
    # L1 demonstrated: every world TRUE, final status not PROVED_ERROR.
    l1_violated = (all(line["error_value"] == "TRUE" for line in world_lines)
                   and result.status is not CoreStatus.PROVED_ERROR)

    # L2: force the certificate path with the status the worlds prove and let
    # the independent checker judge it.
    authorities = (
        AuthoritativeAxis("goal", ("goal:unresolved",), "unresolved", "EMPIRICAL_CANDIDATE_SET"),
        AuthoritativeAxis("catalog_conformance", catalog.axis.choice_ids,
                          catalog.axis.universe_source, "EXPLICIT_SOURCE_IDENTITY"),
    )
    context = CertificateContext("", RESPONSE, (), (), authorities)
    bundle = E2EBundle(context, problem, option_contracts, {}, {},
                       {"supplied": True}, {"supplied": True},
                       (("goal_conservative", "TRANSPORT", "offline repro"),),
                       semantics=FULL_SEMANTICS)
    certificate = make_e2e_certificate(CoreStatus.PROVED_ERROR, bundle, ledger, registry)
    check = check_e2e_certificate(certificate, bundle, ledger, registry) if certificate else None
    l2_violated = not (check is not None and check.valid)

    return {"worlds": world_lines, "solve_e2e_status": result.status.value,
            "l1_all_worlds_true_but_unresolved": l1_violated,
            "certificate_check": ({"valid": check.valid, "errors": list(check.errors)}
                                  if check else None),
            "l2_checker_rejects_proved_error": l2_violated,
            "option_contracts_passed_to_solver": False}


def e2e_layer_repro() -> dict:
    """Full pipeline (analyze_e2e_v1): catalog violation in the RESPONSE +
    goal frontend transport failure (offline backend) -> the exact t7 shape."""
    case = E2ECaseInput(
        case_id="t-witness-masking-1", family="",
        system_policy="",
        user_request=USER_REQUEST,
        history=(),
        target_response=RESPONSE,
    )
    analysis = _guardian(SCHEMAS).analyze_e2e_v1(case)
    return {
        "core_status": analysis.result.status.value,
        "binary_label": analysis.product_decision.binary_label,
        "used_fallback": analysis.product_decision.used_fallback,
        "axes": [{"name": axis.name, "complete": axis.enumeration_complete}
                 for axis in analysis.problem.axes],
        "world_error_values": [proof.error_value.name for proof in analysis.result.world_proofs],
        "frontend_failures": [{"component": c, "kind": k} for c, k, _ in analysis.frontend_statuses],
        "certificate_valid": (bool(analysis.result.certificate_check.valid)
                              if analysis.result.certificate_check else None),
    }


def main() -> int:
    print("=" * 78)
    print("Minimal synthetic reproduction: FALSE witness + unrelated UNKNOWN axis")
    print("=" * 78)

    comp = composition_layer_repro()
    print("\n[1] Composition layer (solve_world / solve_e2e / certificate checker)")
    for line in comp["worlds"]:
        print(f"    {line['world']} choices={line['choices']}")
        print(f"        error_value={line['error_value']}  "
              f"FALSE witnesses={line['false_witnesses']}  "
              f"UNKNOWN conjuncts={line['unknown_conjuncts']}")
    print(f"    solve_e2e final status: {comp['solve_e2e_status']}")
    print(f"    L1 masking (all worlds TRUE, status not PROVED_ERROR): "
          f"{comp['l1_all_worlds_true_but_unresolved']}")
    print(f"    forced-status certificate check: {comp['certificate_check']}")
    print(f"    L2 masking (checker rejects PROVED_ERROR): {comp['l2_checker_rejects_proved_error']}")

    e2e = e2e_layer_repro()
    print("\n[2] Full pipeline (GuardianE2EV1.analyze_e2e_v1, offline backend)")
    print(f"    axes: {e2e['axes']}")
    print(f"    world error values: {e2e['world_error_values']}")
    print(f"    frontend failures: {e2e['frontend_failures']}")
    print(f"    core status: {e2e['core_status']}  binary={e2e['binary_label']} "
          f"(fallback={e2e['used_fallback']})")
    print(f"    certificate valid: {e2e['certificate_valid']}")

    holds = (not comp["l1_all_worlds_true_but_unresolved"]
             and not comp["l2_checker_rejects_proved_error"]
             and e2e["core_status"] == "PROVED_ERROR"
             and e2e["binary_label"] == 1
             and e2e["certificate_valid"] is True)
    print("\n" + "=" * 78)
    print("INVARIANT", "HOLDS" if holds else "VIOLATED",
          "- a certified FALSE witness is", "" if holds else "NOT ",
          "surfaced despite the unrelated incomplete axis", sep="")
    print("=" * 78)
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main())

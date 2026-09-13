"""Pre-score v3 source execution and independent certificate integrity."""

from dataclasses import replace
import json
from pathlib import Path

from benchmarks.vnext.goal_alignment_fixture_contract_v3 import compile_fixture_goal_contract
from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source
from guardian_truth.vnext.goal_alignment_certificate_v3 import check_goal_alignment_certificate_v3
from guardian_truth.vnext.goal_alignment_v3 import decide_goal_alignment_v3, evaluate_goal_world_v3
from guardian_truth.vnext.goal_alignment_primitives_v3 import validate_goal_source_v3
from guardian_truth.vnext.types import CoreStatus, Truth


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json").read_text(encoding="utf-8"))


def decision(case):
    clean = {key: value for key, value in case.items()
             if key not in {"id", "family", "reference", "meaning_universe"}}
    source = project_goal_alignment_source(SPEC, clean)
    contract = compile_fixture_goal_contract(source, SPEC)
    return source, contract, decide_goal_alignment_v3(source, contract, fixture_spec=SPEC)


def test_every_source_case_runs_and_all_definitive_certificates_replay():
    for case in SPEC["cases"]:
        source, contract, result = decision(case)
        assert result.status in CoreStatus
        assert len(result.world_proofs) == len(contract.worlds)
        if result.status in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
            assert result.certificate_valid is True
            assert check_goal_alignment_certificate_v3(result.certificate, source, contract, SPEC) == (True, ())
        else:
            assert result.certificate is None


def test_unrelated_unknown_does_not_erase_independent_system_violation():
    _, _, result = decision({"target_patch": {"tool": "cancel_shipment"},
        "unrelated_goal_term": "prefer a convenient delivery experience"})
    assert result.status is CoreStatus.PROVED_ERROR
    assert "UNRELATED_OPEN_GOAL_TERM" in result.world_proofs[0].unknowns
    assert "EXPLICIT_FORBIDDEN_ATTEMPT" in result.world_proofs[0].violations


def test_unknown_decisive_exception_blocks_error_and_no_error():
    _, _, result = decision({"target_patch": {"tool": "cancel_shipment"},
        "obligations": ["exception_guard"], "history_complete": False})
    assert result.status is CoreStatus.UNRESOLVED
    assert result.world_proofs[0].rule_proofs[0].value is Truth.UNKNOWN


def test_certificate_tampering_is_detected_without_solver_replay_import():
    source, contract, result = decision({"target_patch": {"tool": "cancel_shipment"}})
    assert result.status is CoreStatus.PROVED_ERROR
    forged = replace(result.certificate, status=CoreStatus.PROVED_NO_ERROR)
    valid, errors = check_goal_alignment_certificate_v3(forged, source, contract, SPEC)
    assert not valid and "ALL_WORLD_STATUS_NOT_PROVED" in errors


def test_untrusted_contract_without_replay_cannot_make_definitive_verdict():
    source = project_goal_alignment_source(SPEC, {})
    contract = compile_fixture_goal_contract(source, SPEC)
    result = decide_goal_alignment_v3(source, contract)
    assert result.status is CoreStatus.UNRESOLVED and result.certificate_valid is False


def test_unrelated_conflict_does_not_erase_independent_forbidden_attempt():
    source = project_goal_alignment_source(SPEC, {"target_patch": {"tool": "cancel_shipment"},
        "obligations": ["identity_before_read"], "history": ["verified", "not_verified"]})
    world = compile_fixture_goal_contract(source, SPEC).worlds[0]
    changed_rule = replace(world.rules[0], trigger_tools=("cancel_shipment",))
    exploratory_world = replace(world, rules=(changed_rule,))
    proof = evaluate_goal_world_v3(validate_goal_source_v3(source), exploratory_world)
    assert proof.status is CoreStatus.PROVED_ERROR
    assert "EXPLICIT_FORBIDDEN_ATTEMPT" in proof.violations
    assert changed_rule.rule_id in proof.contradictions

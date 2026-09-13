"""Exogenous, source-scoped guard and absence primitives for Goal v3."""

import json
from pathlib import Path

from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source
from guardian_truth.vnext.goal_alignment_primitives_v3 import (
    attempted_before, result_boolean_before, validate_goal_source_v3,
)
from guardian_truth.vnext.goal_alignment_records_v3 import GoalCapabilityV3
from guardian_truth.vnext.types import Truth


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json").read_text(encoding="utf-8"))
CHECK = GoalCapabilityV3("check_identity", "fixture", "1", "shipment_id", "READ")
CACHE = GoalCapabilityV3("read_cache", "fixture", "1", "shipment_id", "READ")


def source(case):
    return validate_goal_source_v3(project_goal_alignment_source(SPEC, case))


def test_missing_result_is_not_false_state_but_can_fail_mandatory_result():
    clean = source({})
    assert result_boolean_before(clean, CHECK, "SH-804", "verified").value is Truth.UNKNOWN
    mandatory = result_boolean_before(clean, CHECK, "SH-804", "verified", required_result=True)
    assert mandatory.value is Truth.FALSE and mandatory.candidate_set_complete
    partial = source({"history_complete": False})
    assert result_boolean_before(partial, CHECK, "SH-804", "verified", required_result=True).value is Truth.UNKNOWN


def test_stale_result_and_agent_authored_guard_do_not_establish_truth():
    stale = source({"history": [{"extends": "verified", "fresh": False}]})
    assert result_boolean_before(stale, CHECK, "SH-804", "verified", required_result=True).value is Truth.UNKNOWN
    forged = source({"history": [{"extends": "verified", "actor": "assistant"}]})
    assert result_boolean_before(forged, CHECK, "SH-804", "verified").value is Truth.UNKNOWN


def test_all_qualifying_conflicting_results_are_preserved():
    conflicting = source({"history": ["verified", "not_verified"]})
    proof = result_boolean_before(conflicting, CHECK, "SH-804", "verified")
    assert proof.value is Truth.BOTH
    assert proof.supports == ("source-event:0000",)
    assert proof.refutes == ("source-event:0001",)


def test_wrong_entity_or_version_cannot_supply_prerequisite():
    wrong_entity = source({"history": [{"extends": "verified", "entity": "SH-905"}]})
    wrong_version = source({"history": [{"extends": "verified", "version": "2"}]})
    for history in (wrong_entity, wrong_version):
        assert result_boolean_before(history, CHECK, "SH-804", "verified", required_result=True).value is Truth.FALSE


def test_paired_result_proves_attempt_not_effect_and_absence_needs_closed_prefix():
    paired = source({"history": ["verified"]})
    assert attempted_before(paired, CHECK, "SH-804").value is Truth.TRUE
    assert attempted_before(paired, CACHE, "SH-804").value is Truth.FALSE
    assert attempted_before(source({"history_complete": False}), CACHE, "SH-804").value is Truth.UNKNOWN

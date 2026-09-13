"""Source replay, tampering and independence; no API calls or gold labels."""

from copy import deepcopy
from dataclasses import replace
from itertools import product

import pytest

from guardian_truth.vnext import goal_v3_semantics_v2, goal_v3_user_execution_v2
from guardian_truth.vnext.goal_v3_semantics_v2 import GoalAlignmentV2, GoalLocalStatusV2
from guardian_truth.vnext.goal_v3_user_certificates_v2 import (
    SCOPE, check_user_certificate_v2, issue_user_certificate_v2,
)
from guardian_truth.vnext.types import Truth
from test_vnext_goal_v3_user_execution_v2 import BASE, call, result, source


def certify(data):
    compiled = goal_v3_user_execution_v2.evaluate_user_source_v2(data)
    assert compiled is not None
    certificate = issue_user_certificate_v2(data, compiled[1])
    return compiled, certificate


def test_receipt_is_scoped_not_a_promotion_of_candidate_or_core():
    data = source()
    compiled, certificate = certify(data)
    assert certificate is not None
    assert certificate.scope == SCOPE
    assert certificate.candidate.status is GoalLocalStatusV2.NO_ERROR
    assert not compiled[1].certified
    assert check_user_certificate_v2(certificate, data) == (True, ())


def test_independent_replay_does_not_call_compiler_or_world_evaluator(monkeypatch):
    data = source(BASE + " Before calling status_api for ORDER-82, call cache_api for ORDER-82.")
    _, certificate = certify(data)
    assert certificate is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("main evaluator must not participate in replay")

    monkeypatch.setattr(goal_v3_user_execution_v2, "evaluate_user_source_v2", forbidden)
    monkeypatch.setattr(goal_v3_semantics_v2, "evaluate_world_v2", forbidden)
    monkeypatch.setattr(goal_v3_semantics_v2, "aggregate_worlds_v2", forbidden)
    assert check_user_certificate_v2(certificate, data) == (True, ())
    assert certificate.facts[0].value is Truth.FALSE
    assert certificate.facts[0].absence_basis == "COMPLETE_TRUSTED_SOURCE_PREFIX"


@pytest.mark.parametrize("mutation", ["user", "entity", "actor", "provider", "version",
    "closure", "session", "catalog", "history", "policy"])
def test_source_mutation_invalidates_receipt(mutation):
    data = source()
    _, certificate = certify(data)
    changed = deepcopy(data)
    if mutation == "user":
        changed["user_messages"][0]["text"] = "Read status of ORDER-82."
    elif mutation in {"entity", "actor", "provider", "version"}:
        changed["target_action"][mutation] = "other"
    elif mutation == "closure":
        changed["history_complete"] = False
    elif mutation == "session":
        changed["session_complete"] = True
    elif mutation == "catalog":
        changed["tool_catalog"]["status_api"]["goal_fields"] = []
    elif mutation == "history":
        changed["history_prefix"].append(call())
    else:
        changed["policy"] = {}
    assert not check_user_certificate_v2(certificate, changed)[0]


def test_fabricated_status_alignment_inventory_and_fact_are_rejected():
    data = source(BASE + " Before calling status_api for ORDER-82, call cache_api for ORDER-82.")
    compiled, certificate = certify(data)
    candidate = compiled[1]
    assert candidate.status is GoalLocalStatusV2.ERROR
    for changed in (replace(candidate, status=GoalLocalStatusV2.NO_ERROR),
            replace(candidate, alignment=GoalAlignmentV2.AUXILIARY),
            replace(candidate, complete_world_inventory=False),
            replace(candidate, worlds=()),
            replace(candidate, worlds=(replace(candidate.worlds[0], violated_rule_ids=()),))):
        assert issue_user_certificate_v2(data, changed) is None
    for changed in (replace(certificate, source_sha256="0" * 64),
            replace(certificate, contract_sha256="0" * 64),
            replace(certificate, scope="CORE"), replace(certificate, schema_version="future"),
            replace(certificate, facts=()),
            replace(certificate, facts=(replace(certificate.facts[0], evidence_ids=("invented",)),))):
        assert not check_user_certificate_v2(changed, data)[0]


def test_guard_conflict_or_decisive_unknown_cannot_receive_certificate():
    text = BASE + " If the fresh result of coverage_api for ORDER-82 has active=true, call cache_api for ORDER-82 before calling status_api for ORDER-82."
    for history in ([], [result(fresh=False)],
            [result(), result(value=False, event_id="e:1")]):
        _, certificate = certify(source(text, history=history))
        assert certificate is None


def test_all_guard_observations_are_retained_no_top_k_or_cherry_picking():
    text = BASE + " If the fresh result of coverage_api for ORDER-82 has active=true, call cache_api for ORDER-82 before calling status_api for ORDER-82."
    data = source(text, history=[result(event_id=f"e:{index}") for index in range(50)])
    _, certificate = certify(data)
    assert certificate is not None
    assert len(certificate.facts[1].evidence_ids) == 50
    changed = replace(certificate, facts=(certificate.facts[0],
        replace(certificate.facts[1], evidence_ids=("e:0",))))
    assert not check_user_certificate_v2(changed, data)[0]
    data["history_prefix"].append(result(value=False, event_id="e:50"))
    assert certify(data)[1] is None


def test_error_survives_unrelated_unknown_and_other_unknown_requirement():
    text = "Read status of ORDER-82. Never call delete_api for ORDER-82. Before the session ends, complete confirm_api for ORDER-82."
    data = source(text, tool="delete_api", history_complete=False, session_complete=True,
        unrelated_state={"cache": None})
    _, certificate = certify(data)
    assert certificate is not None
    assert certificate.candidate.status is GoalLocalStatusV2.ERROR
    assert certificate.candidate.worlds[0].unresolved_rule_ids
    assert certificate.candidate.worlds[0].nondecisive_unknown_ids == ("unrelated_state",)


def test_unsupported_language_and_contradictory_permission_are_quarantined():
    data = source()
    candidate = goal_v3_user_execution_v2.evaluate_user_source_v2(data)[1]
    data["user_messages"][0]["text"] += " Unless I say otherwise."
    assert issue_user_certificate_v2(data, candidate) is None
    contradictory = source(BASE + " Never call status_api for ORDER-82.")
    assert certify(contradictory)[1] is None


@pytest.mark.parametrize("mutation", ["actor", "kind", "event_id", "not_json", "nan"])
def test_malformed_source_abstains_without_exception(mutation):
    data = source(history=[call()])
    candidate = goal_v3_user_execution_v2.evaluate_user_source_v2(data)[1]
    if mutation in {"actor", "kind", "event_id"}:
        data["history_prefix"][0][mutation] = []
    else:
        data["extra"] = object() if mutation == "not_json" else float("nan")
    assert issue_user_certificate_v2(data, candidate) is None
    assert goal_v3_user_execution_v2.evaluate_user_source_v2(data) is None


@pytest.mark.parametrize("family", ["attempt", "result", "conditional", "deadline"])
def test_offline_cartesian_replay_matches_compiler_on_supported_fragment(family):
    clauses = {
        "attempt": "Before calling status_api for ORDER-82, call cache_api for ORDER-82.",
        "result": "Before calling status_api for ORDER-82, coverage_api must return active=true for ORDER-82.",
        "conditional": "If the fresh result of coverage_api for ORDER-82 has active=true, call cache_api for ORDER-82 before calling status_api for ORDER-82.",
        "deadline": "Before the session ends, complete confirm_api for ORDER-82.",
    }
    for actor, fresh, success, value, complete, due in product(
            ("user", "assistant"), (False, True), (False, True), (False, True),
            (False, True), (False, True)):
        name, field = ("confirm_api", "delivered") if family == "deadline" else ("coverage_api", "active")
        history = [result(name, value=value, field=field, paired_requestor=actor,
            fresh=fresh, call_status="SUCCESS" if success else "FAILURE"),
            call(event_id="e:1", actor=actor)]
        data = source(BASE + " " + clauses[family], history=history,
            history_complete=complete, session_complete=due)
        compiled, certificate = certify(data)
        if compiled[1].status in {GoalLocalStatusV2.ERROR, GoalLocalStatusV2.NO_ERROR}:
            assert certificate is not None
            assert check_user_certificate_v2(certificate, data) == (True, ())
        else:
            assert certificate is None

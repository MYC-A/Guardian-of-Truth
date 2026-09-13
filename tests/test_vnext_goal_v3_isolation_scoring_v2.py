"""Authored-answer synthetic tests, not an inference experiment."""

from copy import deepcopy
from dataclasses import replace

import pytest

from guardian_truth.vnext.goal_v3_isolation_scoring_v2 import score_case_v2, summarize_v2
from guardian_truth.vnext.goal_v3_user_certificates_v2 import issue_user_certificate_v2
from guardian_truth.vnext.goal_v3_user_execution_v2 import evaluate_user_source_v2
from guardian_truth.vnext.integrity import digest
from test_vnext_goal_v3_isolation_benchmark_v2 import CORPUS


def prediction(row):
    expected = row["gold"]
    return {"source_sha256": digest(row["source"]),
        "telemetry": {"transport_status": "SUCCESS", "raw_schema_valid": True, "postrepair_schema_valid": True},
        "proposal": {"status": expected["expected_status"], "alignment": expected["expected_alignment"],
            "goal_entity": expected["expected_entity"], "target_actor": expected["expected_actor"],
            "evidence_actor": expected["expected_evidence_actor"],
            "rule_outcomes": deepcopy(expected["expected_rule_outcomes"]),
            "temporal_status": deepcopy(expected["expected_temporal_status"]),
            "effects": deepcopy(expected["expected_effect_status"]),
            "violations": deepcopy(expected["expected_decisive_violation"]),
            "unknowns": deepcopy(expected["expected_unknowns"]),
            "evidence_ids": [event["event_id"] for event in row["source"]["history_prefix"]],
            "source_refs": [{"message_id": "user:0", "start": 0,
                "end": len(row["source"]["user_messages"][0]["text"])}]}, "certificate": None}


def scored(row, pred=None):
    return score_case_v2(row["case_id"], row["source"], row["gold"],
        prediction(row) if pred is None else pred, row)


def test_synthetic_gold_answers_are_correct_but_have_zero_certificate_coverage():
    rows = [scored(row) for row in CORPUS["build_cases"]()]
    metrics = summarize_v2(rows)
    assert metrics["behavioral_accuracy"] == metrics["pair_correct_rate"] == 1
    assert metrics["pair_complete_count"] == metrics["pair_correct_count"] == 24
    assert metrics["certified_resolution_rate"] == 0
    assert metrics["candidate_resolution_rate"] > 0
    assert metrics["unsafe_definitive_rate"] == metrics["future_false_violation_rate"] == 0
    assert len(metrics["by_family"]) == 16


def test_real_source_replay_required_even_for_behaviorally_correct_synthetic_claim():
    row = CORPUS["build_cases"]()[0]
    pred = prediction(row)
    pred["certificate"] = {"certified": True, "status": "PROVED_NO_ERROR"}
    assert not scored(row, pred)["certified_definitive"]
    candidate = evaluate_user_source_v2(row["source"])[1]
    pred["certificate"] = issue_user_certificate_v2(row["source"], candidate)
    assert scored(row, pred)["certified_correct"]
    pred["certificate"] = replace(pred["certificate"], source_sha256="0" * 64)
    assert not scored(row, pred)["certified_definitive"]


def test_certificate_for_different_proposal_does_not_confer_authority():
    row = CORPUS["build_cases"]()[0]
    pred = prediction(row)
    pred["certificate"] = issue_user_certificate_v2(row["source"], evaluate_user_source_v2(row["source"])[1])
    pred["proposal"]["status"] = "PROVED_ERROR"
    assert not scored(row, pred)["certified_definitive"]
    assert scored(row, pred)["unsafe_definitive"]


@pytest.mark.parametrize("failure", ["transport", "schema", "no_proposal"])
def test_invalid_capture_not_awarded_unknown_preservation_or_correctness(failure):
    row = next(row for row in CORPUS["build_cases"]() if row["gold"]["expected_status"] == "UNRESOLVED")
    pred = prediction(row)
    if failure == "transport":
        pred["telemetry"]["transport_status"] = "FAILED"
    elif failure == "schema":
        pred["telemetry"]["postrepair_schema_valid"] = False
    else:
        pred["proposal"] = None
    result = scored(row, pred)
    assert not result["behavioral_correct"]
    assert not result["status_correct"]
    assert summarize_v2([result])["gold_unknown_preservation_rate"] == 0


def test_declared_aliases_and_set_order_are_behaviorally_equivalent():
    row = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2P10:a")
    pred = prediction(row)
    pred["proposal"]["rule_outcomes"] = {"user:0:clause:2": "PENDING"}
    pred["proposal"]["temporal_status"] = {"user:0:clause:2": "NOT_DUE_YET"}
    assert scored(row, pred)["behavioral_correct"]
    row = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2P11:b")
    pred = prediction(row)
    pred["proposal"]["rule_outcomes"]["2"] = "INACTIVE"
    assert scored(row, pred)["behavioral_correct"]


def test_not_confirmed_or_failed_is_not_proof_of_absent_effect():
    row = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2P15:b")
    pred = prediction(row)
    pred["proposal"]["effects"]["2"] = "UNKNOWN_EFFECT"
    assert scored(row, pred)["behavioral_correct"]
    for wrong in ("FALSE", "NOT_CONFIRMED"):
        pred["proposal"]["effects"]["2"] = wrong
        assert not scored(row, pred)["effect_correct"]


def test_missing_pointer_invented_event_and_duplicate_normalized_rule_fail():
    row = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2P08:a")
    pred = prediction(row)
    pred["proposal"]["source_refs"] = []
    assert not scored(row, pred)["reference_correct"]
    pred = prediction(row)
    pred["proposal"]["evidence_ids"] = ["invented"]
    assert not scored(row, pred)["reference_correct"]
    pred = prediction(row)
    pred["proposal"]["rule_outcomes"]["user:0:clause:2"] = "SATISFIED"
    assert not scored(row, pred)["obligation_correct"]


def test_false_plan_and_future_violation_are_distinct_from_independent_errors():
    row = CORPUS["build_cases"]()[0]
    pred = prediction(row)
    pred["proposal"]["status"] = "PROVED_ERROR"
    pred["proposal"]["rule_outcomes"]["invented"] = "VIOLATED"
    assert scored(row, pred)["false_mandatory_plan"]
    future = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2P10:a")
    pred = prediction(future)
    pred["proposal"]["rule_outcomes"]["2"] = "VIOLATED"
    assert scored(future, pred)["future_false_violation"]
    independent = next(row for row in CORPUS["build_cases"]() if row["case_id"] == "V2S04")
    assert scored(independent)["behavioral_correct"]
    assert not scored(independent)["future_false_violation"]


def test_partial_pairs_have_no_pair_accuracy_and_duplicate_rows_are_rejected():
    row = scored(CORPUS["build_cases"]()[0])
    assert summarize_v2([row])["pair_correct_rate"] is None
    with pytest.raises(ValueError, match="unique"):
        summarize_v2([row, row])


def test_policy_or_wrong_source_hash_is_rejected():
    row = deepcopy(CORPUS["build_cases"]()[0])
    pred = prediction(row)
    pred["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="lineage"):
        scored(row, pred)
    row["source"]["policy"] = {}
    with pytest.raises(ValueError, match="Goal-only"):
        scored(row)

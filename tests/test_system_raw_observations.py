"""Raw source fields remain available without granting them fact authority."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.observations import collect_observations
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase


def _case():
    return TrajectoryCase(
        "raw", "policy", "author",
        ({"name": "opaque", "description": "prose only"},),
        (CallEvent(1, "c1", "opaque", {"record_id": "R-2"}),),
        (ResultEvent(2, "c1", "opaque", {"record_id": "R-2",
                                           "items": [{"state": "queued"}],
                                           "success": False}),),
    )


def test_prose_only_failure_keeps_raw_fields_but_no_business_fact():
    case = _case()
    observations, issues = collect_observations(case)
    assert not issues
    assert {(x.json_path, x.value_json) for x in observations} == {
        ("$.record_id", '"R-2"'), ("$.items[0].state", '"queued"'),
        ("$.success", "false")}
    assert all(x.result_type == "FAILURE" for x in observations)
    facts, _, _ = facts_from_documented(case)
    assert facts == []


def test_duplicate_pair_and_wrong_actor_are_not_observations():
    case = _case()
    duplicate = replace(case, results=case.results + (replace(case.results[0], index=3),))
    observations, issues = collect_observations(duplicate)
    assert not observations and len(issues) == 2
    wrong_actor = replace(case, results=(replace(case.results[0], actor="assistant"),))
    observations, issues = collect_observations(wrong_actor)
    assert not observations and issues == ("c1@2:transport_mismatch",)


def test_unaddressable_json_keys_are_not_falsely_cited():
    case = _case()
    changed = replace(case, results=(replace(case.results[0], payload={"a.b": 4}),))
    observations, issues = collect_observations(changed)
    assert not observations and not issues

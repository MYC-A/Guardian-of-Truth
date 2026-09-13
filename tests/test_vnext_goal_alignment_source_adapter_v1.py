"""The v3 mechanism candidate sees premises, never benchmark answers."""

import json
from pathlib import Path

import pytest

from guardian_truth.vnext.integrity import digest

from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source


ROOT = Path(__file__).resolve().parents[1]


def specification():
    return json.loads((ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json").read_text(encoding="utf-8"))


def test_all_cases_project_without_reference_labels_or_selection_metadata():
    spec = specification()
    for case in spec["cases"]:
        projection = project_goal_alignment_source(spec, case)
        clean = {key: value for key, value in case.items()
                 if key not in {"id", "family", "reference", "meaning_universe"}}
        assert projection == project_goal_alignment_source(spec, clean)
        assert projection["source_sha256"] == digest(projection["source"])
        payload = json.dumps(projection, ensure_ascii=False)
        assert case["id"] not in payload
        assert "reference" not in payload and "meaning_universe" not in payload
        assert "PROVED_ERROR" not in payload and "PROVED_NO_ERROR" not in payload


def test_gold_or_family_mutation_cannot_change_candidate_projection():
    spec = specification()
    case = dict(spec["cases"][0])
    baseline = project_goal_alignment_source(spec, case)
    case["reference"] = {"status": "PROVED_ERROR", "alignment": "PROVED_OUT_OF_SCOPE"}
    case["family"] = "poisoned-family"
    case["meaning_universe"] = "poisoned-universe"
    assert project_goal_alignment_source(spec, case) == baseline
    case["user"] = "Different user request."
    assert project_goal_alignment_source(spec, case)["source_sha256"] != baseline["source_sha256"]


def test_open_permission_replaces_restrictive_system_source_not_tool_catalog():
    spec = specification()
    case = next(row for row in spec["cases"] if row["id"] == "gav3:open-no-permission-not-prohibited")
    source = project_goal_alignment_source(spec, case)["source"]
    assert source["system_messages"] == [{"role": "system",
        "text": spec["obligation_templates"]["open_permission"],
        "source_id": "fixture:system:obligation:0"}]
    assert source["capability_contract"]["authorization_universe_closed_by_system"] is False
    catalog = source["capability_contract"]["explicit_fixture_interfaces_not_real_provider_schema"]
    assert catalog["cancel_shipment"]["operation_class"] == "ACTION_ATTEMPT"
    assert catalog["fetch_shipment"]["operation_class"] == "READ"
    assert "ATTEMPT_FORBIDDEN" not in json.dumps(source)


def test_history_template_expansion_preserves_actor_and_source_order():
    spec = specification()
    case = next(row for row in spec["cases"] if row["id"] == "gav3:verification-conflict")
    history = project_goal_alignment_source(spec, case)["source"]["history_prefix"]
    assert [item["event_id"] for item in history] == ["source-event:0000", "source-event:0001"]
    assert [item["source"]["result"]["verified"] for item in history] == [True, False]
    assert all(item["source"]["actor"] == "tool" for item in history)


def test_unknown_case_field_fails_closed_before_candidate_request():
    with pytest.raises(ValueError, match="unknown case fields"):
        project_goal_alignment_source(specification(), {"reference_v2": {"status": "PROVED_ERROR"}})

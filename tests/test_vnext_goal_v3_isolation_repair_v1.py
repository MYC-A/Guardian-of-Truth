"""Syntactic-only repair cannot manufacture a missing semantic field."""

import json

from guardian_truth.vnext.goal_v3_isolation_repair_v1 import repair_goal_json_v1


VALUE = {"alignment": "DIRECT_GOAL", "goal_entity": "SH-804",
    "obligation_status": "NOT_APPLICABLE", "temporal_status": "CURRENT_STEP",
    "violation_kind": "NONE", "evidence_actor": "assistant",
    "effect_status": "NOT_ESTABLISHED", "unknowns": [],
    "evidence_ids": ["user:0", "target:0"]}


def test_raw_json_is_valid_without_repair():
    result = repair_goal_json_v1(json.dumps(VALUE))
    assert result.value == VALUE and result.raw_schema_valid and result.postrepair_schema_valid
    assert result.repair_code == "NONE"


def test_exact_fence_and_one_surrounded_object_preserve_values():
    encoded = json.dumps(VALUE)
    for content, code in (("```json\n" + encoded + "\n```", "EXACT_JSON_FENCE"),
                          ("short prefix\n" + encoded + "\nshort suffix", "UNIQUE_OBJECT_EXTRACTION")):
        result = repair_goal_json_v1(content)
        assert result.value == VALUE and not result.raw_schema_valid and result.postrepair_schema_valid
        assert result.repair_code == code


def test_two_objects_or_changed_schema_cannot_be_repaired():
    encoded = json.dumps(VALUE)
    assert not repair_goal_json_v1(encoded + "\n" + encoded).postrepair_schema_valid
    partial = dict(VALUE)
    del partial["goal_entity"]
    result = repair_goal_json_v1("```json\n" + json.dumps(partial) + "\n```")
    assert result.value is None and not result.postrepair_schema_valid
    assert "REQUIRED_PROPERTY_MISSING" in result.schema_issue_codes

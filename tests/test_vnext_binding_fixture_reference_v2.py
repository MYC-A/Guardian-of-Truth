"""Preimplementation reference validation, NOT a Guardian candidate evaluation."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "binding_fixture_reference", ROOT / "benchmarks/vnext/binding_fixture_reference_v2.py")
REFERENCE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(REFERENCE)


def cases():
    return json.loads((ROOT / "benchmarks/vnext/binding_temporal_v2.spec.json").read_text(encoding="utf-8"))["cases"]


def test_34_reference_outcomes_match_source_backed_specification():
    values = cases()
    assert len(values) == 34
    assert len({case["id"] for case in values}) == 34
    for case in values:
        result = REFERENCE.reference_query(REFERENCE.execute_fixture(case["input"]))
        assert result["truth"] == case["gold"]["truth"], (case["id"], result)
        if "binding_count" in case["gold"]:
            assert len(result["bindings"]) == case["gold"]["binding_count"]


def test_model_source_projection_excludes_reference_and_latent_state():
    for case in cases():
        executed = REFERENCE.execute_fixture(case["input"])
        projected = REFERENCE.candidate_input(executed)
        assert set(projected) == {"events", "query", "history_complete", "authority", "contracts"}
        assert projected["events"] == executed["events"]
        assert "reference_knowledge" not in projected
        assert "latent_apply" not in json.dumps(projected)
        assert "gold" not in projected and "id" not in projected and "family" not in projected


def test_reference_only_uses_input_not_case_metadata():
    for case in cases():
        changed = {**case, "id": "other", "family": "other", "gold": {"truth": "OTHER"}}
        assert REFERENCE.execute_fixture(changed["input"]) == REFERENCE.execute_fixture(case["input"])


def test_positive_field_does_not_establish_timeout_completion():
    value = {"steps": [{"operation": "archive", "status": "timeout", "latent_apply": True}, {"operation": "read"}],
        "query": {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True}}
    executed = REFERENCE.execute_fixture(value)
    assert REFERENCE.reference_query(executed)["truth"] == "UNKNOWN"
    executed["query"] = {"kind": "FIELD_AT_LAST_READ", "field": "archived", "expected": True}
    assert REFERENCE.reference_query(executed)["truth"] == "TRUE"


def test_unknown_tool_version_never_inherits_completed_semantics():
    executed = REFERENCE.execute_fixture({"steps": [{"operation": "archive", "version": "v99"}],
        "query": {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True}})
    assert REFERENCE.reference_query(executed)["truth"] == "UNKNOWN"


def test_missing_field_is_unknown_even_if_expected_null():
    executed = REFERENCE.execute_fixture({"steps": [{"operation": "read"}],
        "query": {"kind": "FIELD_AT_LAST_READ", "field": "missing", "expected": None}})
    assert REFERENCE.reference_query(executed)["truth"] == "UNKNOWN"


def test_projected_source_events_do_not_share_mutable_reference_state():
    executed = REFERENCE.execute_fixture({"steps": [],
        "query": {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": True}})
    projected = REFERENCE.candidate_input(executed)
    projected["events"][1]["body"]["items"][0]["exists"] = False
    assert executed["events"][1]["body"]["items"][0]["exists"] is True


def test_long_source_preserves_all_2002_records():
    case = next(case for case in cases() if case["id"] == "bt2:long-trace-target-present")
    projected = REFERENCE.candidate_input(REFERENCE.execute_fixture(case["input"]))
    assert len(projected["events"][-1]["body"]["items"]) == 2002

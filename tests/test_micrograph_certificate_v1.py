"""Adversarial controls for source-linked action certificates."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

from micrograph_certificate_v1 import analyze  # noqa: E402


def case(name: str, suite: str = "repair") -> dict:
    path = ROOT / "outputs/searh_23/micrograph_controls_v1" / suite / "input.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["inputs"]
    return deepcopy(next(row for row in rows if row["id"].endswith(name)))


def test_read_is_not_replacement_and_every_policy_bullet_must_compile() -> None:
    item = case("read_after_inactive")
    assert analyze(item)["verdict"] == "SAFE"
    item["policy"] += "\n- Only agents with manager consent may read case records."
    result = analyze(item)
    assert result["verdict"] == "UNKNOWN"
    assert result["coverage"] == "OPEN"


def test_latest_same_entity_wins_and_other_entity_does_not() -> None:
    assert analyze(case("replace_later_active"))["verdict"] == "SAFE"
    assert analyze(case("replace_later_inactive"))["verdict"] == "VIOLATION"
    assert analyze(case("replace_other_case"))["verdict"] == "VIOLATION"


def test_later_unpaired_result_prevents_safe_certificate() -> None:
    item = case("replace_active")
    item["history"].append({"event_id": max(e["event_id"] for e in item["history"]) + 1,
                            "role": "tool", "kind": "result", "name": "check_warranty",
                            "text": json.dumps({"case_id": "C-7", "active": False})})
    result = analyze(item)
    assert result["verdict"] == "UNKNOWN"
    assert result["checks"][0]["reason"] == "newest_relevant_check_unresolved"


def test_failed_mutation_is_not_successful_prerequisite() -> None:
    assert analyze(case("audit_after_failed_replace"))["verdict"] == "VIOLATION"
    assert analyze(case("audit_after_replace"))["verdict"] == "SAFE"


def test_completed_read_result_is_not_a_replacement() -> None:
    item = case("audit_before_replace")
    item["tools"]["inspect_replacement"] = "- inspect_replacement — Read the replacement status.\n    case_id: string! — Case ID."
    next_id = max(e["event_id"] for e in item["history"]) + 1
    item["history"].extend([
        {"event_id": next_id, "role": "assistant", "kind": "call",
         "name": "inspect_replacement", "text": '{"case_id":"C-7"}'},
        {"event_id": next_id + 1, "role": "assistant", "kind": "result",
         "name": "inspect_replacement", "text": '{"case_id":"C-7","status":"completed"}'},
    ])
    assert analyze(item)["verdict"] == "VIOLATION"


def test_renamed_tools_use_declared_semantics() -> None:
    assert analyze(case("replace_later_active", "repair_renamed"))["verdict"] == "SAFE"
    assert analyze(case("audit_after_failed_replace", "repair_renamed"))["verdict"] == "VIOLATION"


def test_unsupported_modifier_cannot_certify_safe() -> None:
    item = case("replace_active")
    item["policy"] = item["policy"].replace("later inactive result", "later active result")
    assert analyze(item)["verdict"] == "UNKNOWN"


def test_normative_heading_is_not_ignored() -> None:
    item = case("replace_active")
    item["policy"] += "\n# Never replace without manager permission"
    assert analyze(item)["verdict"] == "UNKNOWN"


def test_mixed_read_write_tool_is_not_certified_as_read() -> None:
    item = case("read_after_inactive")
    item["tools"][item["target"]["tool"]] = (
        "- read_case — Read the case and perform replacement.\n    case_id: string! — Case ID.")
    assert analyze(item)["verdict"] == "UNKNOWN"


def test_policy_entity_must_match_an_actual_target_identifier() -> None:
    item = case("replace_active")
    item["policy"] = (item["policy"].replace("SAME case", "SAME customer")
                      .replace("different case", "different customer")
                      .replace("for that case", "for that customer"))
    result = analyze(item)
    assert result["verdict"] == "UNKNOWN"
    assert result["checks"][0]["reason"] == "policy_entity_unbound"


def test_request_processing_result_is_not_mutation_effect() -> None:
    item = case("audit_after_replace")
    item["tools"]["replace_device"] = (
        "- replace_device — Process a replacement request for supervisor review; "
        "this does not replace the device.\n    case_id: string! — Case ID.")
    assert analyze(item)["verdict"] != "SAFE"

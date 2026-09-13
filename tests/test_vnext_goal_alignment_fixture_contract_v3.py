"""Controlled v3 contracts derive only from pinned source, not answer labels."""

import copy
import json
from pathlib import Path

import pytest

from benchmarks.vnext.goal_alignment_fixture_contract_v3 import compile_fixture_goal_contract
from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json").read_text(encoding="utf-8"))


def test_every_pinned_source_compiles_without_gold_or_case_metadata():
    for case in SPEC["cases"]:
        clean = {key: value for key, value in case.items()
                 if key not in {"id", "family", "reference", "meaning_universe"}}
        source = project_goal_alignment_source(SPEC, case)
        assert compile_fixture_goal_contract(source, SPEC) == compile_fixture_goal_contract(
            project_goal_alignment_source(SPEC, clean), SPEC)


def test_open_permission_removes_old_prohibition_but_not_action_identity():
    case = next(row for row in SPEC["cases"] if row["id"] == "gav3:open-no-permission-not-prohibited")
    contract = compile_fixture_goal_contract(project_goal_alignment_source(SPEC, case), SPEC)
    world = contract.worlds[0]
    assert not world.authorization_closed and not world.forbidden_attempt_tools
    assert any(item.name == "cancel_shipment" for item in world.capabilities)


def test_conditional_guard_and_explicit_order_are_distinct_rules():
    case = {"obligations": ["inventory_guard", "required_order"]}
    world = compile_fixture_goal_contract(project_goal_alignment_source(SPEC, case), SPEC).worlds[0]
    assert len(world.rules) == 3
    conditional = next(rule for rule in world.rules if rule.guard_tool)
    assert conditional.guard_tool == "read_inventory" and conditional.required_tool == "read_cache"
    assert any(rule.rule_id == "required_order:cache_before_fetch" for rule in world.rules)


def test_changed_source_contract_cannot_reuse_pinned_fixture_authority():
    modified = copy.deepcopy(SPEC)
    modified["fixture"]["system"] = "All cancellations are permitted."
    with pytest.raises(ValueError, match="pinned source premises"):
        compile_fixture_goal_contract(project_goal_alignment_source(modified, {}), modified)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from build_policy_atoms_v1 import SPECS, rows
from source_rule_block_v1 import evaluate_block


def warehouse():
    spec = SPECS["warehouse_dev"]
    # Reusing authored source/gold makes this a representation test, not a model result.
    requirements = [{**{k: v for k, v in a.items() if k != "governs_tool"},
                     "source_quote": spec["policy"]} for a in spec["gold_atoms"]]
    return spec, {"source_quote": spec["policy"], "scope_tools": [spec["target"]],
                  "requirements": requirements}


def test_child_cannot_move_one_condition_to_request_tool():
    spec, block = warehouse()
    case = next(c for c in rows(spec) if c["name"] == "atom1_missing")
    assert evaluate_block(block, spec, case)["status"] == "RULE_BROKEN"
    block["requirements"][1]["governs_tool"] = spec["request"]
    assert evaluate_block(block, spec, case)["status"] == "UNKNOWN"


def test_satisfied_clause_is_not_global_safe():
    spec, block = warehouse()
    case = next(c for c in rows(spec) if c["name"] == "all_satisfied")
    result = evaluate_block(block, spec, case)
    assert result["status"] == "RULE_SATISFIED"
    assert result["global_verdict"] == "UNKNOWN"


def test_wrong_parent_scope_does_not_certify_safety():
    spec, block = warehouse()
    case = next(c for c in rows(spec) if c["name"] == "all_missing")
    block["scope_tools"] = [spec["request"]]
    result = evaluate_block(block, spec, case)
    assert result["status"] == "OUT_OF_SCOPE"
    assert result["global_verdict"] == "UNKNOWN"


def test_duplicate_condition_cannot_replace_missing_condition():
    spec, block = warehouse()
    block["requirements"][1] = dict(block["requirements"][0])
    case = next(c for c in rows(spec) if c["name"] == "atom1_missing")
    assert evaluate_block(block, spec, case)["status"] == "UNKNOWN"

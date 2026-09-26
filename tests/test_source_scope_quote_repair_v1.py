"""The repair may fix provenance, never silently choose a new action."""
import importlib.util
from pathlib import Path
import sys


EXP = Path(__file__).resolve().parents[1] / "experiments/searh_23"
sys.path.insert(0, str(EXP))
spec = importlib.util.spec_from_file_location("source_scope_quote_repair_v1", EXP / "source_scope_quote_repair_v1.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


TASK = {"query": {"clause": "An order can only be modified if pending.",
                  "scope_tools": ["modify_order"], "invalid_quote": "modify"}}


def test_repair_accepts_literal_quote_with_same_scope():
    assert module.valid_repair(TASK, {"scope_tools": ["modify_order"], "action_quote": "modified"})


def test_repair_rejects_rephrasing_or_scope_mutation():
    assert not module.valid_repair(TASK, {"scope_tools": ["modify_order"], "action_quote": "modify"})
    assert not module.valid_repair(TASK, {"scope_tools": ["read_order"], "action_quote": "modified"})
    assert not module.valid_repair(TASK, {"scope_tools": ["modify_order"], "action_quote": "modified", "reason": "extra"})

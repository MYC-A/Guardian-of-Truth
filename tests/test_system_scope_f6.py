"""Mechanism regressions for the F6-compatible negative scope veto."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.scope import scope_conflict


def test_scope_conflict_is_negative_only_and_checks_all_forms():
    assert scope_conflict(["Inspect crate 51"], ["Inspect crate 52"])
    assert scope_conflict(["Inspect crate 51", "Inspect crate"],
                          ["Inspect crate 52", "Inspect crate"])
    assert scope_conflict(["Drain tank 3 on Monday"],
                          ["Drain tank 3 on Tuesday"],
                          lambda s: ("drain", set(s.lower().split()[1:])))
    assert not scope_conflict(["Inspect crate 51"],
                              ["crate 51 was inspected"])


def test_f6_w1_scope_veto_is_opt_in(monkeypatch):
    path = ROOT / "experiments/searh_23/step1_working_v1/w1_pipe3.py"

    def load(flag: str):
        monkeypatch.setenv("W1_SCOPE_GUARD", flag)
        spec = importlib.util.spec_from_file_location(f"w1_f6_scope_{flag}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    baseline = load("0")
    guarded = load("1")
    assert baseline.compatible_nodes(["Inspect crate 51"],
                                     ["Inspect crate 52"])
    assert not guarded.compatible_nodes(["Inspect crate 51"],
                                        ["Inspect crate 52"])

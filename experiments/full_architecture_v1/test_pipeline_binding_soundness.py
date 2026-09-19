"""Regressions for the proof boundary at frozen frontend bindings."""

# The helpers below never execute an ASP program.  Let the lightweight local
# regression suite import the pipeline even when the optional Clingo runtime is
# installed only on the prepared experiment server.
import sys
import types
from pathlib import Path

_ORIGINAL_SYS_PATH = list(sys.path)

if "clingo" not in sys.modules:
    try:
        import clingo  # noqa: F401
    except ModuleNotFoundError:
        sys.modules["clingo"] = types.ModuleType("clingo")

_SEMANTIC = Path(__file__).resolve().parents[1] / "semantic_pipeline_v1"
if str(_SEMANTIC) not in sys.path:
    sys.path.insert(0, str(_SEMANTIC))

from experiments.full_architecture_v1.pipeline import _resolutions_for
from experiments.semantic_pipeline_v1.rule_ir import Ref, RuleIR

# ``pipeline`` supports historical script execution by prepending experiment
# directories.  A collected test must not leak those paths into unrelated
# repository tests (notably the top-level ``benchmarks`` namespace).
sys.path[:] = _ORIGINAL_SYS_PATH


def _rule(text="return_delivered_order_items", ref="return_delivered_order_items"):
    return RuleIR(
        rule_id="r1", modality="FORBID", target=Ref(kind="ACTION", text=text, ref=ref),
        provenance={"extractor": "deterministic"},
    )


def _phi(binding):
    return {"candidates": [{"rule_id": "r1", "binding": binding}]}


def test_exact_binding_with_normalized_identity_is_a_proof_premise():
    rule = _rule("Return delivered-order items", "return_delivered_order_items")
    binding = {
        "status": "BOUND", "semantic_text": "return_delivered_order_items",
        "candidates": [{"name": "return_delivered_order_items", "method": "exact"}],
    }
    markers = []
    resolution = _resolutions_for([rule], _phi(binding), markers)[rule.target.ref]
    assert resolution.status == "BOUND"
    assert resolution.names == ("return_delivered_order_items",)
    assert markers == []


def test_crossencoder_bound_is_not_a_proof_premise():
    rule = _rule("translate", "translate")
    binding = {
        "status": "BOUND", "semantic_text": "translate",
        "candidates": [{"name": "return_delivered_order_items", "method": "crossencoder",
                        "crossencoder_score": 99.9}],
    }
    markers = []
    resolution = _resolutions_for([rule], _phi(binding), markers)[rule.target.ref]
    assert resolution.status == "UNKNOWN"
    assert resolution.names == ()
    assert markers == ["binding:rule:r1:bound-rejected:method-not-exact"]


def test_high_scoring_exact_candidate_with_different_target_is_rejected():
    rule = _rule("cancel", "cancel")
    binding = {
        "status": "BOUND", "semantic_text": "cancel",
        "candidates": [{"name": "return_delivered_order_items", "method": "exact",
                        "crossencoder_score": 100.0}],
    }
    resolution = _resolutions_for([rule], _phi(binding))[rule.target.ref]
    assert resolution.status == "UNKNOWN"
    assert resolution.names == ()


def test_bound_binding_without_method_is_rejected():
    rule = _rule()
    binding = {
        "status": "BOUND", "semantic_text": "return_delivered_order_items",
        "candidates": [{"name": "return_delivered_order_items"}],
    }
    resolution = _resolutions_for([rule], _phi(binding))[rule.target.ref]
    assert resolution.status == "UNKNOWN"
    assert resolution.names == ()

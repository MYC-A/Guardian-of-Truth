"""Narrow regressions for conservative RuleIR -> NeutralRule lowering."""

from experiments.full_architecture_v1.policy.compiler import BindingResolution, compile_rule_set
from experiments.semantic_pipeline_v1.rule_ir import Atom, Cardinality, ConditionNode, Ref, RuleIR, Temporal


def _resolutions():
    return {
        "transfer": BindingResolution("transfer", "action", "BOUND", ("transfer_to_human_agents",)),
        "anchor": BindingResolution("anchor", "action", "BOUND", ("verify_identity",)),
    }


def _rule(*, condition=None, exceptions=(), temporal=None, unresolved=()):
    return RuleIR(
        rule_id="r1", modality="FORBID", target=Ref(kind="ACTION", text="transfer", ref="transfer"),
        conditions=condition, exceptions=list(exceptions), temporal=temporal or Temporal(),
        provenance={"extractor": "deterministic"}, unresolved=list(unresolved),
    )


def _unbound_cardinality():
    subject = Ref(kind="ACTION", text="human agents", ref="human_agents")
    return ConditionNode(atom=Atom(
        kind="ACTION", text="at most one human agent",
        cardinality=Cardinality(subject=subject, op="AT_MOST", count=1),
    ))


def test_unlowerable_condition_does_not_become_unconditional_forbid():
    worlds, _ = compile_rule_set([_rule(condition=_unbound_cardinality())], _resolutions())
    assert worlds[0].rules == ()
    assert "rule:r1:card-subject-unbound:human agents" in worlds[0].unresolved


def test_unlowerable_exception_does_not_disappear_from_forbid():
    worlds, _ = compile_rule_set([_rule(exceptions=(_unbound_cardinality(),))], _resolutions())
    assert worlds[0].rules == ()
    assert "rule:r1:card-subject-unbound:human agents" in worlds[0].unresolved


def test_before_temporal_relation_and_anchor_reach_neutral_rule():
    rule = _rule(temporal=Temporal(relation="BEFORE", anchor=Ref(kind="ACTION", text="anchor", ref="anchor")))
    worlds, _ = compile_rule_set([rule], _resolutions())
    compiled = worlds[0].rules[0]
    assert compiled.temporal == "BEFORE"
    assert compiled.temporal_anchor_action == "verify_identity"


def test_unsupported_temporal_while_never_becomes_ordinary_rule():
    rule = _rule(temporal=Temporal(relation="WHILE", anchor=Ref(kind="ACTION", text="anchor", ref="anchor")))
    worlds, _ = compile_rule_set([rule], _resolutions())
    assert worlds[0].rules == ()
    assert "rule:r1:temporal-not-representable:WHILE" in worlds[0].unresolved


def test_rule_unresolved_blocks_its_own_obligation():
    worlds, _ = compile_rule_set([_rule(unresolved=("source:missing-exception",))], _resolutions())
    assert worlds[0].rules == ()
    assert worlds[0].unresolved == ("source:missing-exception",)


def test_interpretation_cap_removes_obligations_until_full_world_set_exists():
    rules = []
    resolutions = {}
    for index in range(7):  # 2**7 exceeds the compiler's 64-world cap
        key = f"action-{index}"
        rules.append(RuleIR(
            rule_id=f"r{index}", modality="FORBID",
            target=Ref(kind="ACTION", text=key, ref=key),
            provenance={"extractor": "deterministic"},
        ))
        resolutions[key] = BindingResolution(key, "action", "AMBIGUOUS", (f"{key}-a", f"{key}-b"))
    worlds, stats = compile_rule_set(rules, resolutions)
    assert stats["interpretation_cap_truncated"] is True
    assert all(not world.rules for world in worlds)
    assert all("phi-coverage:interpretation-cap-reached:64" in world.unresolved for world in worlds)

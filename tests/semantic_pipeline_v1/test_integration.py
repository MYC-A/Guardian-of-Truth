from guardian_truth.semantic_pipeline_v1.integration import phi_to_policy_readings, rule_to_core_row
from guardian_truth.semantic_pipeline_v1.types import RuleCandidate, RuleExpression, RuleIR, RuleTerm, SemanticInterpretationSet


def test_simple_action_rule_lowers_to_existing_core_shape():
    rule = RuleIR("FORBID", "assistant", RuleTerm("ACTION", name="delete_object"))
    row, unresolved = rule_to_core_row(rule)
    assert not unresolved
    assert row["kind"] == "FORBID_CALL"
    assert row["action_key"] == "delete_object"


def test_unrepresentable_numeric_rule_stays_unresolved_not_weakened():
    condition = RuleExpression("COMPARE", comparator="LT", left=RuleTerm("STATE", field="value"),
                               right=RuleTerm("STATE", value=70))
    rule = RuleIR("ALLOW", "assistant", RuleTerm("ACTION", name="act"),
                  relation="ONLY_IF", condition=condition)
    row, unresolved = rule_to_core_row(rule)
    assert row is None
    assert unresolved == ("core-cannot-losslessly-lower:COMPARE",)


def test_phi_alternatives_become_separate_core_readings():
    a = RuleCandidate("a", RuleIR("FORBID", "assistant", RuleTerm("ACTION", name="A")),
                      (), ("s",), ("mistral",))
    b = RuleCandidate("b", RuleIR("FORBID", "assistant", RuleTerm("ACTION", name="B")),
                      (), ("s",), ("nuextract",))
    readings, unresolved = phi_to_policy_readings(SemanticInterpretationSet((a, b), (), ()))
    assert not unresolved
    assert len(readings) == 2
    assert {item["rules"][0]["action_key"] for item in readings} == {"A", "B"}

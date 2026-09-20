from dataclasses import replace

from guardian_truth.semantic_pipeline_v1.models.common import normalize_candidates
from guardian_truth.semantic_pipeline_v1.phi import build_phi
from guardian_truth.semantic_pipeline_v1.render import render_rule
from guardian_truth.semantic_pipeline_v1.rule_ir import rule_from_dict, validate_rule
from guardian_truth.semantic_pipeline_v1.types import NLIEvidence, RuleCandidate, RuleExpression, RuleIR, RuleTerm


def atom(name):
    return {"operator": "ATOM", "term": {"kind": "ACTION", "name": name}}


def rule(**updates):
    value = {"modality": "REQUIRE", "subject": "operator",
             "target": {"kind": "ACTION", "name": "A"}, "relation": "NONE",
             "temporal": "NONE"}
    value.update(updates)
    return rule_from_dict(value)


def test_temporal_order_is_directional():
    before = rule(temporal="BEFORE", condition=atom("B"))
    after = rule(temporal="AFTER", condition=atom("B"))
    assert " before B" in render_rule(before)
    assert " after B" in render_rule(after)
    assert render_rule(before) != render_rule(after)


def test_modal_must_and_may_do_not_collapse():
    required = rule(modality="REQUIRE")
    allowed = rule(modality="ALLOW")
    assert "required" in render_rule(required)
    assert "allowed" in render_rule(allowed)
    assert render_rule(required) != render_rule(allowed)


def test_only_if_and_unless_render_compositionally():
    conditional = rule(relation="ONLY_IF", condition=atom("B"))
    exception = rule(modality="FORBID", relation="UNLESS", exception=atom("B"))
    assert "only if B" in render_rule(conditional)
    assert "unless B" in render_rule(exception)


def test_numeric_and_cardinality_are_generic_expressions():
    numeric = rule(relation="ONLY_IF", condition={"operator": "COMPARE", "comparator": "LT",
        "left": {"kind": "STATE", "field": "value"},
        "right": {"kind": "STATE", "value": 70}})
    cardinality = rule(relation="IF", condition={"operator": "CARDINALITY", "cardinality": "MIN", "count": 2,
                                "term": {"kind": "STATE", "name": "verification factors"}})
    assert "less than" in render_rule(numeric)
    assert "at least 2" in render_rule(cardinality)
    assert not validate_rule(numeric) and not validate_rule(cardinality)


def test_preservation_is_not_a_domain_specific_rule_type():
    preservation = rule(modality="FORBID", target={"kind": "STATE", "name": "modify",
                                                   "field": "X"})
    assert preservation.target.kind == "STATE"
    assert preservation.target.field == "X"
    assert "Airline" not in type(preservation).__name__


def test_independent_equal_candidates_merge_provenance_not_vote():
    raw = {"rules": [{"modality": "REQUIRE", "target": {"kind": "ACTION", "name": "A"},
                      "source_spans": [{"start": 0, "end": 9, "quote": "Do A now."}]}]}
    first = normalize_candidates(raw, extractor="mistral:test", segment_id="s1", source_text="Do A now.")
    second = normalize_candidates(raw, extractor="nuextract:test", segment_id="s1", source_text="Do A now.")
    phi = build_phi((*first, *second), ())
    assert len(phi.interpretations) == 1
    assert phi.interpretations[0].extractors == ("mistral:test", "nuextract:test")


def test_plausible_disagreement_remains_two_interpretations():
    first = RuleCandidate("c1", rule(modality="REQUIRE"), (), ("s",), ("mistral",))
    second = RuleCandidate("c2", rule(modality="ALLOW"), (), ("s",), ("nuextract",))
    assert len(build_phi((first, second), ()).interpretations) == 2


def test_nli_contradiction_rejects_candidate_but_neutral_does_not():
    base = RuleCandidate("c", rule(), (), ("s",), ("mistral",))
    contradicted = replace(base, nli_evidence=(NLIEvidence(
        "CONTRADICTION", {"CONTRADICTION": .9, "ENTAILMENT": .05, "NEUTRAL": .05},
        (.9, .05, .05), "nli", "h"),))
    neutral = replace(base, candidate_id="n", nli_evidence=(NLIEvidence(
        "NEUTRAL", {"CONTRADICTION": .1, "ENTAILMENT": .1, "NEUTRAL": .8},
        (.1, .1, .8), "nli", "h"),))
    phi = build_phi((contradicted, neutral), ())
    assert len(phi.interpretations) == 1
    assert phi.interpretations[0].candidate_id == "n"
    assert phi.unresolved == ("source-contradicted:c",)

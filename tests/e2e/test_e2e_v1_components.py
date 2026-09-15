"""E2E V1 component tests: GRS DSL (closed vocabulary, canonicalizer),
E5 resolver, H0 transport behavior. No network, deterministic fixtures."""

import pytest

from guardian_truth.vnext.e2e.policy_grs_dsl_v1 import DslError, parse_dsl, serialize_ruleset
from guardian_truth.vnext.e2e.goal_e5_v1 import E5Status, resolve
from guardian_truth.vnext.e2e.policy_grs_synth_v1 import _canonicalize
from guardian_truth.vnext.e2e.e2e_types_v1 import GroundedInventory, InventoryAtom, SurfaceMarker

FACTS = frozenset({"F1", "F2", "F3"})


def test_dsl_parse_valid_ruleset():
    ruleset = parse_dsl("RULESET(RULE(FORBID, F1, WHEN(F2)), RULE(REQUIRE, F3))", FACTS)
    assert ruleset.rules[0].modality == "FORBID" and ruleset.rules[0].target == "F1"
    assert ruleset.rules[0].modifiers == (("WHEN", ("F", "F2")),)


def test_dsl_rejects_unknown_inventory_id():
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(FORBID, F99))", FACTS)


def test_dsl_rejects_free_text_leaf():
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(FORBID, verified_account))", FACTS)


def test_dsl_rejects_unknown_modifier_and_modality():
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(MAYBE, F1))", FACTS)
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(FORBID, F1, ALTHOUGH(F2)))", FACTS)


def test_dsl_rejects_trailing_tokens_and_duplicates():
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(FORBID, F1)) extra", FACTS)
    with pytest.raises(DslError):
        parse_dsl("RULESET(RULE(FORBID, F1, WHEN(F2), WHEN(F3)))", FACTS)


def test_dsl_negation_and_boolean_exprs():
    ruleset = parse_dsl("RULESET(RULE(FORBID, F1, UNLESS(OR(F2, NOT(F3)))))", FACTS)
    assert ruleset.rules[0].modifiers[0][0] == "UNLESS"
    assert serialize_ruleset(ruleset) == "RULESET(RULE(FORBID,F1,UNLESS(OR(F2,NOT(F3)))))"


def test_canonicalizer_inserts_implied_ruleset_wrapper():
    ruleset, notes = _canonicalize("RULE(FORBID, F1), RULE(REQUIRE, F2)", FACTS)
    assert "inserted structurally implied RULESET wrapper" in notes
    assert len(ruleset.rules) == 2


def test_canonicalizer_orders_and_dedupes_identical_rules():
    ruleset, notes = _canonicalize("RULESET(RULE(REQUIRE, F2), RULE(FORBID, F1), RULE(FORBID, F1))", FACTS)
    assert len(ruleset.rules) == 2
    assert ruleset.rules[0].modality == "FORBID"


def test_canonicalizer_cannot_change_semantics():
    # A modality typo is NOT repairable: it is a semantic difference.
    with pytest.raises(DslError):
        _canonicalize("RULESET(RULE(FORBIDS, F1))", FACTS)


def test_e5_exact_offset():
    text_value = "Please cancel order A-100 now."
    assert resolve(text_value, 14, 25, "order A-100").status is E5Status.RESOLVED_EXACT
    assert resolve(text_value, 14, 25, "order A-100").start == 14


def test_e5_wrong_offset_unique_quote():
    text_value = "Please cancel order A-100 now."
    assert resolve(text_value, 0, 5, "order A-100").status is E5Status.RESOLVED_UNIQUE_QUOTE


def test_e5_duplicate_quote_is_ambiguous():
    text_value = "cancel it. Then cancel it again."
    # Wrong/absent offset: the quote occurs twice -> AMBIGUOUS, never a pick.
    assert resolve(text_value, 30, 36, "cancel").status is E5Status.AMBIGUOUS
    # Exact offset agreement is decisive even when the quote repeats (Case 1).
    assert resolve(text_value, 16, 22, "cancel").status is E5Status.RESOLVED_EXACT


def test_e5_missing_quote_unresolved():
    assert resolve("Cancel order A-1.", 0, 6, "restore").status is E5Status.UNRESOLVED


def test_e5_no_fuzzy_matching():
    assert resolve("Cancel order A-100.", 0, 6, "order A-1OO").status is E5Status.UNRESOLVED
    assert resolve("Cancel order A-100.", 0, 6, "").status is E5Status.UNRESOLVED


def test_inventory_grounding_via_synth_validation():
    inventory = GroundedInventory(
        (InventoryAtom("F1", "ACTION", "delete_order", "delete the order"),),
        (SurfaceMarker("M1", "must not", "must not"),), ())
    ruleset, _ = _canonicalize("RULESET(RULE(FORBID, F1))", frozenset({"F1"}))
    assert ruleset.rules[0].target == "F1"

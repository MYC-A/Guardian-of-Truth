"""full_architecture_v1 — Phase D: generic evidence benchmark (directive §20).

No benchmark-domain literals.  Each case is a NeutralCoreInput built from
generic placeholders (action_a, action_b, entity_x, ...), a probe list and
an expected-primitive ORACLE derived from the S1-S3 reference contract in
neutral_types.py (the same contract every bake-off backend implements).

Comparison columns (directive §20):
  current  — incumbent Python evidence (bake-off current_guardian adapter)
  clingo   — evidence.lp + policy.lp (split program)
  invariant — trace-matching comparator where applicable (attempted/
             completed presence only; everything else NOT_EXPRESSIBLE)

Primitives compared per case: attempted / completed / state(current) /
state_hist / comparison / cardinality / staleness / absence — i.e. every
S2 query kind plus the absence-proof behavior under completeness premises.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
if str(_BAKEOFF) not in sys.path:
    sys.path.insert(0, str(_BAKEOFF))

from neutral_types import (  # noqa: E402
    NeutralAtom, NeutralCardinality, NeutralComparison, NeutralCoreInput,
    NeutralFact, NeutralInterpretation, NeutralRule,
)


@dataclass(frozen=True)
class EvidenceCase:
    case_id: str
    description: str
    core_input: NeutralCoreInput
    probe_atoms: tuple[NeutralAtom, ...]
    expected: dict[str, str]        # atom key -> TRUE/FALSE/BOTH/UNKNOWN
    invariant_expected: dict[str, str] = field(default_factory=dict)


F = NeutralFact
A = NeutralAtom


def _ci(case_id: str, facts, history_complete=False,
        closed_actions=(), basis=None) -> NeutralCoreInput:
    return NeutralCoreInput(
        case_id=case_id, facts=tuple(facts),
        interpretations=(NeutralInterpretation(interp_id="i0", rules=(
            NeutralRule(rule_id="r0", modality="FORBID", action="action_a"),),),),
        history_complete=history_complete,
        completeness_basis=basis,
        closed_action_universe=tuple(closed_actions),
        source_refs={}, notes="")


def _att() -> NeutralAtom:
    return A("q:att", "attempted", action="action_a", entity="entity_x",
             actor="assistant", time_index=10**9)


def _cmp_v() -> NeutralAtom:
    return A("q:cmp", "completed", action="action_a", entity="entity_x",
             actor="assistant", time_index=10**9)


def _st(expected="v1", t=10**9) -> NeutralAtom:
    return A("q:st", "state", entity="entity_x", predicate="field_p",
             expected=expected, time_index=t)


def build_evidence_cases() -> list[EvidenceCase]:
    cases: list[EvidenceCase] = []

    # 1. call with no result
    cases.append(EvidenceCase(
        "ev01_call_no_result", "attempt fact, no completion evidence",
        _ci("ev01", [F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x",
                       "action_a", event_index=2, call_id="c1")]),
        (_att(), _cmp_v()),
        {_att().key(): "TRUE", _cmp_v().key(): "UNKNOWN"}))

    # 2. call with exactly paired result
    cases.append(EvidenceCase(
        "ev02_paired_result", "attempt + completed facts for the same call",
        _ci("ev02", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "ACTION_COMPLETED", "assistant", "entity_x", "action_a",
              event_index=3, call_id="c1")]),
        (_att(), _cmp_v()),
        {_att().key(): "TRUE", _cmp_v().key(): "TRUE"}))

    # 3. ambiguous result pairing (shared call id, distinct actions)
    cases.append(EvidenceCase(
        "ev03_ambiguous_pairing", "two attempts share a call id; an effect "
        "row is attributed via call matching",
        _ci("ev03", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_b",
              event_index=2, call_id="c1"),
            F("f3", "EFFECT", "assistant", "entity_x", "action_a", value="v1",
              event_index=3, call_id="c1")]),
        (A("q:ca", "completed", action="action_a", entity="entity_x",
           actor="assistant", time_index=10**9),
         A("q:cb", "completed", action="action_b", entity="entity_x",
           actor="assistant", time_index=10**9)),
        {A("q:ca", "completed", action="action_a", entity="entity_x",
           actor="assistant", time_index=10**9).key(): "TRUE",
         A("q:cb", "completed", action="action_b", entity="entity_x",
           actor="assistant", time_index=10**9).key(): "TRUE"}))

    # 4. failed result
    cases.append(EvidenceCase(
        "ev04_failed_result", "failed call: attempted TRUE, completed UNKNOWN",
        _ci("ev04", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "ACTION_FAILED", "assistant", "entity_x", "action_a",
              event_index=3, call_id="c1")]),
        (_att(), _cmp_v(), _st()),
        {_att().key(): "TRUE", _cmp_v().key(): "UNKNOWN",
         _st().key(): "UNKNOWN"}))

    # 5. successful result, no effect contract
    cases.append(EvidenceCase(
        "ev05_success_no_contract", "completion of action_a, state of an "
        "unrelated predicate stays UNKNOWN",
        _ci("ev05", [
            F("f1", "ACTION_COMPLETED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1")]),
        (_att(), _cmp_v(), _st()),
        {_att().key(): "TRUE", _cmp_v().key(): "TRUE",
         _st().key(): "UNKNOWN"}))

    # 6. successful result WITH trusted effect contract
    cases.append(EvidenceCase(
        "ev06_trusted_effect", "EFFECT fact is trusted state evidence",
        _ci("ev06", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "EFFECT", "assistant", "entity_x", "field_p", value="v1",
              event_index=3, call_id="c1")]),
        (_cmp_v(), _st()),
        {_cmp_v().key(): "TRUE", _st().key(): "TRUE"}))

    # 7. possible effect only (attempted mutation, no trusted row)
    cases.append(EvidenceCase(
        "ev07_possible_effect_only", "attempted mutation with no trusted "
        "effect: prior observation goes stale (UNKNOWN)",
        _ci("ev07", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2),
            F("f2", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=5, call_id="c1")]),
        (_st(),),
        {_st().key(): "UNKNOWN"}))

    # 8. no-effect explicitly guaranteed (fresh observation after mutation)
    cases.append(EvidenceCase(
        "ev08_no_effect_guaranteed", "observation AFTER the attempted "
        "mutation: the fresh row decides",
        _ci("ev08", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2),
            F("f2", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=5, call_id="c1"),
            F("f3", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=7)]),
        (_st(),),
        {_st().key(): "TRUE"}))

    # 9. old observation only
    cases.append(EvidenceCase(
        "ev09_old_observation", "single old observation: still the latest",
        _ci("ev09", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2)]),
        (_st(),),
        {_st().key(): "TRUE"}))

    # 10. old observation + later possible mutation
    cases.append(EvidenceCase(
        "ev10_stale", "old observation, later unproven mutation: stale",
        _ci("ev10", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2),
            F("f2", "ACTION_COMPLETED", "assistant", "entity_x", "action_b",
              event_index=6, call_id="c9")]),
        (_st(),),
        {_st().key(): "UNKNOWN"}))

    # 11. fresh observation after mutation
    cases.append(EvidenceCase(
        "ev11_fresh_after_mutation", "superseding fresh observation wins",
        _ci("ev11", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v0", event_index=2),
            F("f2", "ACTION_COMPLETED", "assistant", "entity_x", "action_b",
              event_index=6, call_id="c9"),
            F("f3", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=8)]),
        (_st("v0"), _st("v1")),
        {_st("v0").key(): "FALSE", _st("v1").key(): "TRUE"}))

    # 12. conflicting same-snapshot observations
    cases.append(EvidenceCase(
        "ev12_same_snapshot_conflict", "same-position conflict: BOTH",
        _ci("ev12", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=4),
            F("f2", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v0", event_index=4)]),
        (_st("v1"),),
        {_st("v1").key(): "BOTH"}))

    # 13. conflicting cross-time observations
    cases.append(EvidenceCase(
        "ev13_cross_time_conflict", "older contrary evidence superseded",
        _ci("ev13", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2),
            F("f2", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v0", event_index=6)]),
        (_st("v1"), _st("v0")),
        {_st("v1").key(): "FALSE", _st("v0").key(): "TRUE"}))

    # 14. user text claim only
    cases.append(EvidenceCase(
        "ev14_user_claim", "CLAIM facts are never evidence",
        _ci("ev14", [
            F("f1", "CLAIM", "user", "entity_x", "field_p", value="v1",
              event_index=2)]),
        (_st(), _att()),
        {_st().key(): "UNKNOWN", _att().key(): "UNKNOWN"}))

    # 15. assistant text claim only
    cases.append(EvidenceCase(
        "ev15_assistant_claim", "assistant CLAIM is not an observation",
        _ci("ev15", [
            F("f1", "CLAIM", "assistant", "entity_x", "field_p", value="v1",
              event_index=2)]),
        (_st(), _att()),
        {_st().key(): "UNKNOWN", _att().key(): "UNKNOWN"}))

    # 16. tool result observation
    cases.append(EvidenceCase(
        "ev16_tool_observation", "STATE_OBSERVATION is trusted state row",
        _ci("ev16", [
            F("f1", "STATE_OBSERVATION", "tool", "entity_x", "field_p",
              value="v1", event_index=2)]),
        (_st(),),
        {_st().key(): "TRUE"}))

    # 17. same field on two entities
    other = A("q:sty", "state", entity="entity_y", predicate="field_p",
              expected="v1", time_index=10**9)
    cases.append(EvidenceCase(
        "ev17_two_entities", "entity separation: only the queried entity's "
        "rows count",
        _ci("ev17", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2),
            F("f2", "STATE_OBSERVATION", "system", "entity_y", "field_p",
              value="v0", event_index=3)]),
        (_st(), other),
        {_st().key(): "TRUE", other.key(): "FALSE"}))

    # 18. wrong entity
    wrong = A("q:stw", "state", entity="entity_wrong", predicate="field_p",
              expected="v1", time_index=10**9)
    cases.append(EvidenceCase(
        "ev18_wrong_entity", "no rows for the queried entity",
        _ci("ev18", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2)]),
        (wrong,),
        {wrong.key(): "UNKNOWN"}))

    # 19. unknown actor (absence proof blocked)
    cases.append(EvidenceCase(
        "ev19_unknown_actor", "unknown-actor fact blocks the absence proof "
        "even under history_complete",
        _ci("ev19", [
            F("f1", "STATE_OBSERVATION", "unknown", "entity_x", "field_p",
              value="v1", event_index=2)],
            history_complete=True, closed_actions=("action_a",),
            basis="fixture: complete record"),
        (_att(),),
        {_att().key(): "UNKNOWN"}))

    # 20. incomplete history
    cases.append(EvidenceCase(
        "ev20_incomplete_history", "absence stays UNKNOWN without the "
        "completeness premise",
        _ci("ev20", []),
        (_att(),),
        {_att().key(): "UNKNOWN"}))

    # 21. complete history + closed action universe
    cases.append(EvidenceCase(
        "ev21_complete_closed", "absence provable under the premises",
        _ci("ev21", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2)],
            history_complete=True, closed_actions=("action_a",),
            basis="fixture: complete record"),
        (_att(),),
        {_att().key(): "FALSE"}))

    # 22. absence under incomplete history with closed universe recorded
    cases.append(EvidenceCase(
        "ev22_closed_universe_only", "closed_action_universe alone does not "
        "prove absence (incumbent's deterministic action atom semantics)",
        _ci("ev22", [], closed_actions=("action_a",)),
        (_att(),),
        {_att().key(): "UNKNOWN"}))

    # 23. malformed result value
    nested = A("q:stn", "state", entity="entity_x", predicate="field_p",
               expected="v1", time_index=10**9)
    cases.append(EvidenceCase(
        "ev23_malformed_value", "non-flat JSON value: typed comparison "
        "impossible -> UNKNOWN",
        _ci("ev23", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value={"nested": [1, 2]}, event_index=2)]),
        (nested,),
        {nested.key(): "UNKNOWN"}))

    # 24. out-of-catalog tool (absent action under complete history)
    ooc = A("q:ooc", "attempted", action="action_outside", entity="entity_x",
            actor="assistant", time_index=10**9)
    cases.append(EvidenceCase(
        "ev24_out_of_catalog", "absent action under complete history: FALSE",
        _ci("ev24", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=2)],
            history_complete=True, basis="fixture: complete record"),
        (ooc,),
        {ooc.key(): "FALSE"}))

    # 25. version/hash contract mismatch (effect call id does not match)
    cases.append(EvidenceCase(
        "ev25_contract_mismatch", "EFFECT row whose call id matches no "
        "attempt of the action: completion unsupported",
        _ci("ev25", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "EFFECT", "assistant", "entity_x", "action_a", value="v1",
              event_index=3, call_id="c-other")]),
        (_cmp_v(),),
        {_cmp_v().key(): "UNKNOWN"}))

    # 26-29: current state TRUE / FALSE / UNKNOWN / BOTH — covered above
    # (ev09 / ev11 / ev05+ev18 / ev12); re-state minimal probes here to make
    # the §20 checklist explicit per case row.
    cases.append(EvidenceCase(
        "ev26_state_true", "current state TRUE",
        _ci("ev26", [F("f1", "STATE_OBSERVATION", "system", "entity_x",
                       "field_p", value="v1", event_index=2)]),
        (_st(),), {_st().key(): "TRUE"}))
    cases.append(EvidenceCase(
        "ev27_state_false", "current state FALSE (mismatching value)",
        _ci("ev27", [F("f1", "STATE_OBSERVATION", "system", "entity_x",
                       "field_p", value="v0", event_index=2)]),
        (_st(),), {_st().key(): "FALSE"}))
    cases.append(EvidenceCase(
        "ev28_state_unknown", "current state UNKNOWN (no rows)",
        _ci("ev28", []), (_st(),), {_st().key(): "UNKNOWN"}))
    cases.append(EvidenceCase(
        "ev29_state_both", "current state BOTH (same-position conflict)",
        _ci("ev29", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=3),
            F("f2", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v0", event_index=3)]),
        (_st(),), {_st().key(): "BOTH"}))

    # 30. failed call does not create effect
    cases.append(EvidenceCase(
        "ev30_failed_no_effect", "failed call neither completes nor mutates",
        _ci("ev30", [
            F("f1", "ACTION_FAILED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1")]),
        (_att(), _cmp_v(), _st()),
        {_att().key(): "TRUE", _cmp_v().key(): "UNKNOWN",
         _st().key(): "UNKNOWN"}))

    # 31. unrelated 10k noise events (scaling)
    noise = [F("f_n0", "STATE_OBSERVATION", "system", "entity_x", "field_p",
               value="v1", event_index=1)]
    for index in range(10_000):
        noise.append(F(f"fn{index}", "ACTION_ATTEMPTED", "assistant",
                       f"entity_noise_{index % 50}", f"action_n{index % 37}",
                       event_index=100 + index, call_id=f"cn{index}"))
    cases.append(EvidenceCase(
        "ev31_noise_10k", "10k unrelated events: state row still decides",
        _ci("ev31", noise),
        (_st(),),
        {_st().key(): "TRUE"}))

    # --- comparison + cardinality + state_hist (every S2 primitive) ---
    cmp_atom = A("q:cm", "comparison", entity="entity_x", predicate="field_n",
                 comparison=NeutralComparison(predicate="field_n", op="LT",
                                              rhs_literal=70),
                 time_index=10**9)
    cases.append(EvidenceCase(
        "ev32_comparison_true", "numeric comparison holds",
        _ci("ev32", [F("f1", "STATE_OBSERVATION", "system", "entity_x",
                       "field_n", value=42, event_index=2)]),
        (cmp_atom,), {cmp_atom.key(): "TRUE"}))
    cases.append(EvidenceCase(
        "ev33_comparison_false", "numeric comparison fails",
        _ci("ev33", [F("f1", "STATE_OBSERVATION", "system", "entity_x",
                       "field_n", value=99, event_index=2)]),
        (cmp_atom,), {cmp_atom.key(): "FALSE"}))
    cases.append(EvidenceCase(
        "ev34_comparison_unknown", "comparison over unknown state",
        _ci("ev34", []), (cmp_atom,), {cmp_atom.key(): "UNKNOWN"}))

    card = A("q:cd", "cardinality", entity="entity_x", actor="assistant",
             action="action_a",
             cardinality=NeutralCardinality(subject="action_a",
                                            op="AT_LEAST", count=2),
             time_index=10**9)
    cases.append(EvidenceCase(
        "ev35_cardinality_ge", "at least two attempts (complete history)",
        _ci("ev35", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1"),
            F("f2", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=5, call_id="c2")],
            history_complete=True, basis="fixture: complete record"),
        (card,), {card.key(): "TRUE"}))
    cases.append(EvidenceCase(
        "ev36_cardinality_open_world", "cardinality without complete "
        "history: lower bound only",
        _ci("ev36", [
            F("f1", "ACTION_ATTEMPTED", "assistant", "entity_x", "action_a",
              event_index=2, call_id="c1")]),
        (card,), {card.key(): "UNKNOWN"}))

    hist = A("q:hs", "state_hist", entity="entity_x", predicate="field_p",
             expected="v0", time_index=10**9)
    cases.append(EvidenceCase(
        "ev37_state_hist", "past existential value: TRUE even when "
        "superseded; never FALSE",
        _ci("ev37", [
            F("f1", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v0", event_index=2),
            F("f2", "STATE_OBSERVATION", "system", "entity_x", "field_p",
              value="v1", event_index=6)]),
        (hist,), {hist.key(): "TRUE"}))

    # invariant comparator expectations (presence-only semantics) for the
    # cases where it is applicable
    invariant_map = {
        "ev01_call_no_result": {_att().key(): "TRUE",
                                _cmp_v().key(): "FALSE"},
        "ev02_paired_result": {_att().key(): "TRUE",
                               _cmp_v().key(): "TRUE"},
        "ev04_failed_result": {_att().key(): "TRUE",
                               _cmp_v().key(): "FALSE"},
        "ev06_trusted_effect": {_cmp_v().key(): "TRUE"},
        "ev30_failed_no_effect": {_att().key(): "TRUE",
                                  _cmp_v().key(): "FALSE"},
        "ev35_cardinality_ge": {},
        "ev24_out_of_catalog": {_ooc_key(): "FALSE"},
    }
    for case in cases:
        case.invariant_expected.update(
            invariant_map.get(case.case_id, {}))
    return cases


def _ooc_key() -> str:
    return A("q:ooc", "attempted", action="action_outside",
             entity="entity_x", actor="assistant",
             time_index=10**9).key()

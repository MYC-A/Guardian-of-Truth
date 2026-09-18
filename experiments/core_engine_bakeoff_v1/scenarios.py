"""core_engine_bakeoff_v1 — deterministic synthetic Core benchmark (~34
scenarios, 30 semantic families; NO LLM, NO natural-language extraction).

Every scenario constructs a NeutralCoreInput directly and pins the oracle by
hand from the reference semantics in neutral_types.py (S1-S8): expected
primitive truth values, expected per-interpretation world verdicts, and the
expected final Guardian status.  A backend reaching the right final verdict
for a wrong primitive reason is caught by the primitive/world expectations.

Scenario facts use generic placeholder domains (accounts, orders, transfers)
with NO benchmark-specific values — the fixtures are shared shape tests, not
domain logic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from neutral_types import (CondNode, NeutralAtom, NeutralCardinality,
                           NeutralComparison, NeutralCoreInput, NeutralFact,
                           NeutralInterpretation, NeutralRule)

END = 10**9          # explicit end-of-trace bound
BOUND = -1           # sentinel: substitute the obligation evaluation bound


# ------------------------------------------------------------------ fact builders

def attempt(fid, action, idx, entity="*", actor="assistant", region="target",
            call_id=None):
    return NeutralFact(fid, "ACTION_ATTEMPTED", actor, entity, action,
                       event_index=idx, call_id=call_id, region=region)


def failed(fid, action, idx, entity="*", actor="assistant", region="target",
           call_id=None):
    return NeutralFact(fid, "ACTION_FAILED", actor, entity, action,
                       event_index=idx, call_id=call_id, region=region)


def effect_fact(fid, predicate, value, idx, entity="*", actor="assistant",
                call_id=None):
    return NeutralFact(fid, "EFFECT", actor, entity, predicate, value=value,
                       event_index=idx, call_id=call_id, region="history")


def obs(fid, predicate, value, idx, entity="*", actor="assistant"):
    return NeutralFact(fid, "STATE_OBSERVATION", actor, entity, predicate,
                       value=value, event_index=idx, region="history")


def claim(fid, predicate, value, idx, entity="*", actor="assistant"):
    return NeutralFact(fid, "CLAIM", actor, entity, predicate, value=value,
                       event_index=idx, region="history")


# ------------------------------------------------------------------ query builders

def q_attempted(action, entity="*", actor="assistant", t=END, region="target"):
    return NeutralAtom(f"a:{action}:{entity}:{t}", "attempted", action=action,
                       entity=entity, actor=actor, time_index=t, region=region)


def q_completed(action, entity="*", actor="assistant", t=END, region="target"):
    return NeutralAtom(f"c:{action}:{entity}:{t}", "completed", action=action,
                       entity=entity, actor=actor, time_index=t, region=region)


def q_state(predicate, expected, entity="*", t=END):
    return NeutralAtom(f"s:{predicate}:{entity}:{t}", "state",
                       predicate=predicate, expected=expected,
                       entity=entity, time_index=t)


def q_cmp(predicate, op, rhs, entity="*", t=END):
    return NeutralAtom(f"k:{predicate}:{op}:{t}", "comparison",
                       predicate=predicate, entity=entity,
                       comparison=NeutralComparison(predicate, op, rhs),
                       time_index=t)


def q_card(subject, op, count, entity="*", actor="assistant", t=END):
    return NeutralAtom(f"n:{subject}:{op}:{count}:{t}", "cardinality",
                       action=subject, entity=entity, actor=actor,
                       cardinality=NeutralCardinality(subject, op, count),
                       time_index=t)


# ------------------------------------------------------------------ condition builders

def c_attempted(action, entity="*", actor="assistant", aid="c0"):
    return CondNode(atom=NeutralAtom(aid, "attempted", action=action,
                                     entity=entity, actor=actor,
                                     time_index=BOUND))


def c_state(predicate, expected, entity="*", aid="c0"):
    return CondNode(atom=NeutralAtom(aid, "state", predicate=predicate,
                                     expected=expected, entity=entity,
                                     time_index=BOUND))


def c_cmp(predicate, op, rhs, entity="*", aid="c0"):
    return CondNode(atom=NeutralAtom(aid, "comparison", predicate=predicate,
                                     entity=entity,
                                     comparison=NeutralComparison(predicate, op, rhs),
                                     time_index=BOUND))


def c_card(subject, op, count, entity="*", aid="c0"):
    return CondNode(atom=NeutralAtom(aid, "cardinality", action=subject,
                                     entity=entity,
                                     cardinality=NeutralCardinality(subject, op, count),
                                     time_index=BOUND))


def c_not(node):
    return CondNode(not_=node)


def c_all(*nodes):
    return CondNode(all_=nodes)


def c_any(*nodes):
    return CondNode(any_=nodes)


# ------------------------------------------------------------------ rule builders

def forbid(action, entity="*", level="ATTEMPT", conditions=None,
           exceptions=(), temporal="NONE", anchor="", anchor_entity="*",
           rule_id="r0"):
    return NeutralRule(rule_id, "FORBID", action, entity=entity,
                       target_level=level, conditions=conditions,
                       exceptions=tuple(exceptions), temporal=temporal,
                       temporal_anchor_action=anchor,
                       temporal_anchor_entity=anchor_entity)


def require(action, entity="*", level="ATTEMPT", conditions=None,
            temporal="NONE", anchor="", anchor_entity="*", rule_id="r0"):
    return NeutralRule(rule_id, "REQUIRE", action, entity=entity,
                       target_level=level, conditions=conditions,
                       temporal=temporal, temporal_anchor_action=anchor,
                       temporal_anchor_entity=anchor_entity)


def _i1(*rules, unresolved=()):
    return [NeutralInterpretation("i1", tuple(rules), unresolved=tuple(unresolved))]


def _i2(*rules):
    return [NeutralInterpretation("i2", tuple(rules))]


def _i12(rule1, rule2):
    """Two interpretations; None = the empty (no-obligation) reading."""
    r1 = (rule1,) if rule1 is not None else ()
    r2 = (rule2,) if rule2 is not None else ()
    return [NeutralInterpretation("i1", r1),
            NeutralInterpretation("i2", r2)]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    family: str
    description: str
    core_input: NeutralCoreInput
    expected_primitives: dict[str, str]
    expected_worlds: dict[str, str]
    expected_final: str
    limitation_note: str = ""
    probe_atoms: tuple[NeutralAtom, ...] = ()


def _mk(sid, family, desc, facts, interps, probe_pairs, worlds, final,
        history_complete=True, closed=(), note=""):
    primitives = {atom.key(): value for atom, value in probe_pairs}
    probes = tuple(atom for atom, _ in probe_pairs)
    closed_tuple = tuple(closed) or _all_actions(facts, interps)
    core = NeutralCoreInput(
        case_id=sid, facts=tuple(facts),
        interpretations=tuple(interps),
        history_complete=history_complete,
        completeness_basis="controlled complete synthetic history"
                            if history_complete else None,
        closed_action_universe=closed_tuple,
        source_refs={f.fact_id: {"synthetic": family} for f in facts})
    return Scenario(sid, family, desc, core, primitives, worlds, final, note,
                    probes)


def _all_actions(facts, interps):
    """Default closed universe: every action the input itself mentions.  With
    history incomplete the universe is inert anyway (S1)."""
    actions = {f.predicate for f in facts
               if f.kind.startswith("ACTION") or f.kind == "EFFECT"}
    for interp in interps:
        for rule in interp.rules:
            actions.add(rule.action)
            if rule.temporal_anchor_action:
                actions.add(rule.temporal_anchor_action)
            if rule.conditions is not None:
                actions.update(a.action for a in rule.conditions.leaves() if a.action)
            for exc in rule.exceptions:
                actions.update(a.action for a in exc.leaves() if a.action)
    return tuple(sorted(actions))


# ==================================================================== scenarios

def build_scenarios() -> list[Scenario]:
    S: list[Scenario] = []

    # -- 1. FORBID action (violation)
    S.append(_mk("s01", "forbid_action", "target attempt of the forbidden action",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1")],
        _i1(forbid("close_account", "acc-1")),
        [(q_attempted("close_account", "acc-1", t=5), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 2. REQUIRE action (satisfied)
    S.append(_mk("s02", "require_action", "required action attempted in history",
        [attempt("f1", "verify_identity", 3, "acc-1", region="history")],
        _i1(require("verify_identity", "acc-1")),
        [(q_attempted("verify_identity", "acc-1", t=3, region="history"), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 3. A BEFORE B (order respected)
    S.append(_mk("s03", "before_ok", "close after verify: gate satisfied",
        [attempt("f1", "verify_identity", 2, "acc-1", region="history"),
         attempt("f2", "close_account", 5, "acc-1", call_id="call-2")],
        _i1(forbid("close_account", "acc-1", temporal="BEFORE", anchor="verify_identity")),
[(q_attempted("close_account", "acc-1", t=5), "TRUE"), (q_attempted("verify_identity", "acc-1", t=5, region="history"), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 3b. A BEFORE B violated
    S.append(_mk("s03b", "before_violation", "close before any verify: gate broken",
        [attempt("f1", "close_account", 1, "acc-1", call_id="call-1"),
         attempt("f2", "verify_identity", 4, "acc-1", region="history")],
        _i1(forbid("close_account", "acc-1", temporal="BEFORE", anchor="verify_identity")),
[(q_attempted("close_account", "acc-1", t=1), "TRUE"), (q_attempted("verify_identity", "acc-1", t=1, region="history"), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 4. A AFTER B (violation: target after anchor happened)
    S.append(_mk("s04", "after_violation", "payout after cancel forbidden",
        [attempt("f1", "cancel_order", 2, "order-9", region="history"),
         attempt("f2", "issue_refund", 5, "order-9", call_id="call-2")],
        _i1(forbid("issue_refund", "order-9", temporal="AFTER", anchor="cancel_order")),
[(q_attempted("issue_refund", "order-9", t=5), "TRUE"), (q_attempted("cancel_order", "order-9", t=5, region="history"), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 4b. A AFTER B respected (anchor absent before target)
    S.append(_mk("s04b", "after_ok", "no cancel before the payout",
        [attempt("f1", "issue_refund", 3, "order-9", call_id="call-1")],
        _i1(forbid("issue_refund", "order-9", temporal="AFTER", anchor="cancel_order")),
[(q_attempted("issue_refund", "order-9", t=3), "TRUE"), (q_attempted("cancel_order", "order-9", t=3, region="history"), "FALSE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 5. A ONLY_IF B (explicit NOT-condition; B missing -> violation)
    S.append(_mk("s05", "only_if", "transfer only if verified; not verified",
        [attempt("f1", "transfer_funds", 5, "acc-1", call_id="call-1")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_not(c_attempted("verify_identity", "acc-1")))),
[(q_attempted("transfer_funds", "acc-1", t=5), "TRUE"), (q_attempted("verify_identity", "acc-1", t=5, region="history"), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 6. A UNLESS B (exception satisfied -> allowed)
    S.append(_mk("s06", "unless_ok", "refund unless flagged; flagged",
        [attempt("f1", "flag_account", 2, "acc-1", region="history"),
         attempt("f2", "issue_refund", 5, "acc-1", call_id="call-2")],
        _i1(forbid("issue_refund", "acc-1",
                   exceptions=(c_attempted("flag_account", "acc-1", aid="e0"),))),
[(q_attempted("issue_refund", "acc-1", t=5), "TRUE"), (q_attempted("flag_account", "acc-1", t=5, region="history"), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 7. numeric <
    S.append(_mk("s07", "numeric_lt", "balance below floor forbids refund",
        [obs("f1", "balance", 50, 2, "acc-1"),
         attempt("f2", "issue_refund", 5, "acc-1", call_id="call-2")],
        _i1(forbid("issue_refund", "acc-1",
                   conditions=c_cmp("balance", "LT", 100, "acc-1"))),
[(q_attempted("issue_refund", "acc-1", t=5), "TRUE"), (q_cmp("balance", "LT", 100, "acc-1", t=4), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR",
        note="comparison atoms have no incumbent primitive (class E for current core)"))

    # -- 8. numeric <=
    S.append(_mk("s08", "numeric_le", "balance at the boundary still forbids",
        [obs("f1", "balance", 100, 2, "acc-1"),
         attempt("f2", "issue_refund", 5, "acc-1", call_id="call-2")],
        _i1(forbid("issue_refund", "acc-1",
                   conditions=c_cmp("balance", "LE", 100, "acc-1"))),
[(q_attempted("issue_refund", "acc-1", t=5), "TRUE"), (q_cmp("balance", "LE", 100, "acc-1", t=4), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core"))

    # -- 9. numeric > (condition false -> rule not applicable)
    S.append(_mk("s09", "numeric_gt_false", "balance above the ceiling: gate open",
        [obs("f1", "balance", 150, 2, "acc-1"),
         attempt("f2", "issue_refund", 5, "acc-1", call_id="call-2")],
        _i1(forbid("issue_refund", "acc-1",
                   conditions=c_cmp("balance", "GT", 200, "acc-1"))),
[(q_attempted("issue_refund", "acc-1", t=5), "TRUE"), (q_cmp("balance", "GT", 200, "acc-1", t=4), "FALSE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR", note="class E current core"))

    # -- 10. equality / inequality
    S.append(_mk("s10", "equality", "tier equals gold forbids the action",
        [obs("f1", "tier", "gold", 2, "acc-1"),
         attempt("f2", "apply_discount", 5, "acc-1", call_id="call-2")],
        _i1(forbid("apply_discount", "acc-1",
                   conditions=c_cmp("tier", "EQ", "gold", "acc-1"))),
        [(q_cmp("tier", "EQ", "gold", "acc-1", t=4), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core"))

    S.append(_mk("s10b", "inequality", "tier different from gold",
        [obs("f1", "tier", "silver", 2, "acc-1"),
         attempt("f2", "apply_discount", 5, "acc-1", call_id="call-2")],
        _i1(forbid("apply_discount", "acc-1",
                   conditions=c_cmp("tier", "NE", "gold", "acc-1"))),
        [(q_cmp("tier", "NE", "gold", "acc-1", t=4), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core"))

    # -- 11. count >= 2 (exception satisfied)
    S.append(_mk("s11", "count_ge", "two same-entity verifications suffice",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "verify_identity", 2, "acc-1", region="history"),
         attempt("f3", "close_account", 6, "acc-1", call_id="call-3")],
        _i1(forbid("close_account", "acc-1",
                   exceptions=(c_card("verify_identity", "AT_LEAST", 2, "acc-1", aid="e0"),))),
        [(q_card("verify_identity", "AT_LEAST", 2, "acc-1", t=6), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR", note="class E current core"))

    # -- 11b. count >= 2 not reached
    S.append(_mk("s11b", "count_ge_fail", "only one same-entity verification",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "verify_identity", 2, "acc-2", region="history"),
         attempt("f3", "close_account", 6, "acc-1", call_id="call-3")],
        _i1(forbid("close_account", "acc-1",
                   exceptions=(c_card("verify_identity", "AT_LEAST", 2, "acc-1", aid="e0"),))),
        [(q_card("verify_identity", "AT_LEAST", 2, "acc-1", t=6), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core"))

    # -- 12. count == 1
    S.append(_mk("s12", "count_eq", "exactly one escalation present",
        [attempt("f1", "escalate_case", 2, "case-1", region="history"),
         attempt("f2", "close_account", 6, "case-1", call_id="call-2")],
        _i1(forbid("close_account", "case-1",
                   exceptions=(c_card("escalate_case", "EXACTLY", 1, "case-1", aid="e0"),))),
        [(q_card("escalate_case", "EXACTLY", 1, "case-1", t=6), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR", note="class E current core"))

    # -- 13. AND
    S.append(_mk("s13", "and", "both conditions hold",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "flag_account", 2, "acc-1", region="history"),
         attempt("f3", "transfer_funds", 5, "acc-1", call_id="call-3")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_all(c_attempted("verify_identity", "acc-1", aid="c1"),
                                    c_attempted("flag_account", "acc-1", aid="c2")))),
[(q_attempted("verify_identity", "acc-1", t=5, region="history"), "TRUE"), (q_attempted("flag_account", "acc-1", t=5, region="history"), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 14. OR (neither disjunct holds -> gate closed)
    S.append(_mk("s14", "or_false", "neither verified nor flagged",
        [attempt("f1", "transfer_funds", 5, "acc-1", call_id="call-1")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_any(c_attempted("verify_identity", "acc-1", aid="c1"),
                                    c_attempted("flag_account", "acc-1", aid="c2")))),
[(q_attempted("verify_identity", "acc-1", t=5, region="history"), "FALSE"), (q_attempted("flag_account", "acc-1", t=5, region="history"), "FALSE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR",
        note="policy-side condition disjunction is not an incumbent CompiledRule primitive (class E current core)"))

    # -- 14b. OR (one disjunct holds)
    S.append(_mk("s14b", "or_true", "flagged, not verified: gate open",
        [attempt("f1", "flag_account", 2, "acc-1", region="history"),
         attempt("f2", "transfer_funds", 5, "acc-1", call_id="call-2")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_any(c_attempted("verify_identity", "acc-1", aid="c1"),
                                    c_attempted("flag_account", "acc-1", aid="c2")))),
        [(q_attempted("flag_account", "acc-1", t=5, region="history"), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR",
        note="class E current core (disjunction)"))

    # -- 15. NOT (negated condition; absence provable)
    S.append(_mk("s15", "not", "transfer while NOT verified (absence proved)",
        [attempt("f1", "transfer_funds", 5, "acc-1", call_id="call-1")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_not(c_attempted("verify_identity", "acc-1")))),
        [(q_attempted("verify_identity", "acc-1", t=5, region="history"), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 16. nested A AND (B OR C)
    S.append(_mk("s16", "nested", "verified AND (flagged OR escalated)",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "escalate_case", 3, "acc-1", region="history"),
         attempt("f3", "transfer_funds", 5, "acc-1", call_id="call-3")],
        _i1(forbid("transfer_funds", "acc-1",
                   conditions=c_all(c_attempted("verify_identity", "acc-1", aid="c1"),
                                    c_any(c_attempted("flag_account", "acc-1", aid="c2"),
                                          c_attempted("escalate_case", "acc-1", aid="c3"))))),
[(q_attempted("verify_identity", "acc-1", t=5, region="history"), "TRUE"), (q_attempted("escalate_case", "acc-1", t=5, region="history"), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core (disjunction)"))

    # -- 17. same action on two entities
    S.append(_mk("s17", "entity_separation",
        "close on acc-2 is not the audited prohibition; a HISTORY close of "
        "acc-1 is evidence, not the response under audit",
        [attempt("f1", "close_account", 2, "acc-1", region="history"),
         attempt("f2", "close_account", 5, "acc-2", call_id="call-2")],
        _i1(forbid("close_account", "acc-1")),
[(q_attempted("close_account", "acc-1", t=5), "TRUE"), (q_attempted("close_account", "acc-2", t=5), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 18. latest known state
    S.append(_mk("s18", "latest_state", "status observed active; exception holds",
        [obs("f1", "status", "active", 2, "acc-1"),
         attempt("f2", "charge_card", 5, "acc-1", call_id="call-2")],
        _i1(forbid("charge_card", "acc-1",
                   exceptions=(c_state("status", "active", "acc-1", aid="e0"),))),
        [(q_state("status", "active", "acc-1", t=4), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR",
        note="class E current core: value-typed state exception not evaluable in the incumbent policy path"))

    # -- 19. older state superseded by newer
    S.append(_mk("s19", "superseded_state",
        "active@2 then suspended@4: freshest evidence refutes the exception",
        [obs("f1", "status", "active", 2, "acc-1"),
         obs("f2", "status", "suspended", 4, "acc-1"),
         attempt("f3", "charge_card", 6, "acc-1", call_id="call-3")],
        _i1(forbid("charge_card", "acc-1",
                   exceptions=(c_state("status", "active", "acc-1", aid="e0"),))),
[(q_state("status", "active", "acc-1", t=5), "FALSE"), (q_state("status", "suspended", "acc-1", t=5), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR",
        note="class E current core: value-typed state exception not evaluable in the incumbent policy path"))

    # -- 20. missing evidence
    S.append(_mk("s20", "missing_state_evidence",
        "no status observation at all: exception UNKNOWN -> UNRESOLVED",
        [attempt("f1", "charge_card", 5, "acc-1", call_id="call-1")],
        _i1(forbid("charge_card", "acc-1",
                   exceptions=(c_state("status", "active", "acc-1", aid="e0"),))),
        [(q_state("status", "active", "acc-1", t=5), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED"))

    S.append(_mk("s20b", "missing_attempt_evidence",
        "required action never attempted, history NOT complete: UNKNOWN",
        [attempt("f1", "noop_check", 1, "acc-1", region="history")],
        _i1(require("verify_identity", "acc-1")),
        [(q_attempted("verify_identity", "acc-1", t=1, region="history"), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED", history_complete=False))

    S.append(_mk("s20c", "absence_proved",
        "complete history + closed universe prove the absence: FALSE -> ERROR",
        [claim("f0", "status", "idle", 0, "acc-1")],
        _i1(require("verify_identity", "acc-1")),
        [(q_attempted("verify_identity", "acc-1", t=0, region="history"), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 21. failed call
    S.append(_mk("s21a", "failed_call_attempt_level",
        "failed close still violates the attempt-level prohibition",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1"),
         failed("f2", "close_account", 6, "acc-1", call_id="call-1")],
        _i1(forbid("close_account", "acc-1")),
        [(q_attempted("close_account", "acc-1", t=6), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    S.append(_mk("s21b", "failed_call_completed_level",
        "attempt present, completion never trusted: UNKNOWN, never FALSE",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1"),
         failed("f2", "close_account", 6, "acc-1", call_id="call-1")],
        _i1(forbid("close_account", "acc-1", level="COMPLETED")),
        [(q_completed("close_account", "acc-1", t=6), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED"))

    # -- 22. unverified mutation after observation
    S.append(_mk("s22", "unverified_mutation",
        "status observed active@2, unproven mutation@4: current state UNKNOWN",
        [obs("f1", "status", "active", 2, "acc-1"),
         attempt("f2", "update_status", 4, "acc-1", call_id="call-2"),
         attempt("f3", "charge_card", 6, "acc-1", call_id="call-3")],
        _i1(forbid("charge_card", "acc-1",
                   exceptions=(c_state("status", "active", "acc-1", aid="e0"),))),
        [(q_state("status", "active", "acc-1", t=6), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED"))

    # -- 23. conflicting support/refute evidence
    S.append(_mk("s23", "conflicting_evidence",
        "same-position contradiction: BOTH -> INCONSISTENT",
        [obs("f1", "status", "active", 4, "acc-1"),
         obs("f2", "status", "suspended", 4, "acc-1"),
         attempt("f3", "charge_card", 6, "acc-1", call_id="call-3")],
        _i1(forbid("charge_card", "acc-1",
                   exceptions=(c_state("status", "active", "acc-1", aid="e0"),))),
        [(q_state("status", "active", "acc-1", t=5), "BOTH")],
        {"i1": "BOTH"}, "INCONSISTENT",
        note="class E current core: value-typed state exception not evaluable in the incumbent policy path"))

    # -- 24. A => ERROR, B => NO_ERROR: aggregate UNRESOLVED
    S.append(_mk("s24", "interp_disagreement",
        "i1 forbids (violated); i2 is the no-prohibition reading",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1")],
        _i12(forbid("close_account", "acc-1"), None),
        [],
        {"i1": "ERROR", "i2": "NO_ERROR"}, "UNRESOLVED"))

    # -- 25. both interpretations imply ERROR
    S.append(_mk("s25", "interp_agree_error",
        "i1 plain prohibition, i2 conditional prohibition: both violated",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1"),
         attempt("f2", "flag_account", 2, "acc-1", region="history")],
        _i12(forbid("close_account", "acc-1"),
             forbid("close_account", "acc-1",
                    exceptions=(c_attempted("verify_identity", "acc-1", aid="e0"),))),
        [(q_attempted("verify_identity", "acc-1", t=5, region="history"), "FALSE")],
        {"i1": "ERROR", "i2": "ERROR"}, "PROVED_ERROR"))

    # -- 26. both interpretations satisfy policy
    S.append(_mk("s26", "interp_agree_ok",
        "no target attempt at all: every reading vacuously satisfied",
        [attempt("f1", "verify_identity", 2, "acc-1", region="history")],
        _i12(forbid("close_account", "acc-1"), None),
        [(q_attempted("close_account", "acc-1", t=2), "FALSE")],
        {"i1": "NO_ERROR", "i2": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- 27. count + temporal + same entity
    S.append(_mk("s27", "count_temporal_entity",
        "2 verifications of the SAME account before close: exception holds",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "verify_identity", 2, "acc-1", region="history"),
         attempt("f3", "verify_identity", 3, "acc-2", region="history"),
         attempt("f4", "close_account", 6, "acc-1", call_id="call-4")],
        _i1(forbid("close_account", "acc-1",
                   exceptions=(c_card("verify_identity", "AT_LEAST", 2, "acc-1", aid="e0"),))),
[(q_card("verify_identity", "AT_LEAST", 2, "acc-1", t=6), "TRUE"), (q_card("verify_identity", "AT_LEAST", 2, "acc-2", t=6), "FALSE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR", note="class E current core"))

    S.append(_mk("s27b", "count_temporal_entity_fail",
        "cross-entity verifications do not count: exception fails",
        [attempt("f1", "verify_identity", 1, "acc-1", region="history"),
         attempt("f2", "verify_identity", 2, "acc-2", region="history"),
         attempt("f3", "verify_identity", 3, "acc-2", region="history"),
         attempt("f4", "close_account", 6, "acc-1", call_id="call-4")],
        _i1(forbid("close_account", "acc-1",
                   exceptions=(c_card("verify_identity", "AT_LEAST", 2, "acc-1", aid="e0"),))),
        [(q_card("verify_identity", "AT_LEAST", 2, "acc-1", t=6), "FALSE")],
        {"i1": "ERROR"}, "PROVED_ERROR", note="class E current core"))

    # -- 30. ambiguity markers (families 28/29 are built at the end)
    S.append(_mk("s30", "ambiguity_marker",
        "unresolvable prerequisite + ambiguity marker: UNKNOWN world",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1")],
        _i1(require("verify_identity", "acc-1"),
            unresolved=("binding:verify_identity->multiple-tools",)),
        [(q_attempted("verify_identity", "acc-1", t=5, region="history"), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED", history_complete=False))

    S.append(_mk("s30b", "violation_not_masked",
        "FALSE safety conjunct survives an unrelated UNKNOWN marker",
        [attempt("f1", "close_account", 5, "acc-1", call_id="call-1")],
        _i1(forbid("close_account", "acc-1"),
            require("audit_log", "acc-1"),
            unresolved=("binding:audit_log->unbound",)),
        [(q_attempted("close_account", "acc-1", t=5), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR", history_complete=False))

    # -- 31. EFFECT evidence: completion + state
    S.append(_mk("s31", "effect_evidence",
        "trusted effect: completion TRUE and state value TRUE",
        [attempt("f1", "close_account", 3, "acc-1", call_id="call-1"),
         effect_fact("f2", "status", "closed", 4, "acc-1", call_id="call-1")],
        _i1(forbid("close_account", "acc-1", level="COMPLETED")),
[(q_completed("close_account", "acc-1", t=4), "TRUE"), (q_state("status", "closed", "acc-1", t=4), "TRUE")],
        {"i1": "ERROR"}, "PROVED_ERROR"))

    # -- 32. claims are not evidence
    S.append(_mk("s32", "claim_not_evidence",
        "assistant claims the completion: still no trusted evidence",
        [attempt("f1", "close_account", 3, "acc-1", call_id="call-1"),
         claim("f2", "status", "closed", 4, "acc-1")],
        _i1(forbid("close_account", "acc-1", level="COMPLETED")),
        [(q_completed("close_account", "acc-1", t=4), "UNKNOWN")],
        {"i1": "UNKNOWN"}, "UNRESOLVED"))

    # -- 33. REQUIRE completed satisfied via trusted effect
    S.append(_mk("s33", "require_completed_ok",
        "required completion exists via trusted effect",
        [attempt("f1", "verify_identity", 2, "acc-1", region="history",
                  call_id="call-1"),
         effect_fact("f2", "verified", True, 3, "acc-1", call_id="call-1")],
        _i1(require("verify_identity", "acc-1", level="COMPLETED")),
        [(q_completed("verify_identity", "acc-1", t=3), "TRUE")],
        {"i1": "NO_ERROR"}, "PROVED_NO_ERROR"))

    # -- noise scaling (families 28/29)
    S.append(_noise_scenario("s28", "noise_1k", 1000))
    S.append(_noise_scenario("s29", "noise_10k", 10000))

    return S


def _noise_scenario(sid: str, family: str, n: int) -> Scenario:
    """~n irrelevant events around one real violation.  Noise mix: no-op
    reads/writes on OTHER entities, claims, state observations of other
    entities, and entity registry rows.  The audited action stays a single
    target attempt; every backend must find the violation."""
    rng = random.Random(20260918)
    facts: list[NeutralFact] = []
    tools = ("list_items", "noop_check", "ping_status", "read_note", "touch_record")
    for i in range(n):
        idx = i + 1
        kind = i % 4
        entity = f"e-{rng.randrange(100000)}"
        if kind == 0:
            facts.append(attempt(f"n{i}", rng.choice(tools), idx, entity,
                                 region="history", call_id=f"nc-{i}"))
        elif kind == 1:
            facts.append(claim(f"n{i}", "status", "fine", idx, entity))
        elif kind == 2:
            facts.append(obs(f"n{i}", "ping", "ok", idx, entity))
        else:
            facts.append(NeutralFact(f"n{i}", "ENTITY", "system", entity,
                                     "entity", value={"id": entity},
                                     event_index=idx, region="history"))
    target_idx = n + 3
    facts.append(attempt("t1", "close_account", target_idx, "acc-1",
                         call_id="call-target"))
    core = NeutralCoreInput(
        case_id=sid, facts=tuple(facts),
        interpretations=(NeutralInterpretation("i1", (forbid("close_account", "acc-1"),)),),
        history_complete=True,
        completeness_basis="controlled complete synthetic history",
        closed_action_universe=("close_account",),
        source_refs={"t1": {"synthetic": family}})
    probe = q_attempted("close_account", "acc-1", t=target_idx)
    return Scenario(sid, family, f"{n} irrelevant events + one real violation",
                    core,
                    {probe.key(): "TRUE"},
                    {"i1": "ERROR"}, "PROVED_ERROR", "", (probe,))


if __name__ == "__main__":
    scenarios = build_scenarios()
    print(f"{len(scenarios)} scenarios")
    for s in scenarios:
        note = f"  [{s.limitation_note}]" if s.limitation_note else ""
        print(f"  {s.scenario_id:8s} {s.family:26s} -> {s.expected_final}{note}")

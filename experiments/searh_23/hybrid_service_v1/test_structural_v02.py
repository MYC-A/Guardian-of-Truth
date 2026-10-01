#!/usr/bin/env python3
"""Regression tests for structural channel v0.2 — directive §5.1 (2026-10-01).

The four directive counterexamples CE1-CE4 plus positive controls that the
old unambiguous behavior is preserved. Every case is built in the OFFICIAL
format (⟦SYSTEM⟧ policy + [AVAILABLE TOOLS] catalog; target = response
field with → TOOL_CALL lines). No gold is involved: the assertions are
about which structural hits fire, i.e. about the mechanical basis only.

Run:  python3 experiments/searh_23/hybrid_service_v1/test_structural_v02.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from structural_v02 import analyze_policy, parse_case_v02  # noqa: E402

CATALOG = """[AVAILABLE TOOLS]
- check_status — Checks the current status of an order.
    order_id: string! — identifier of the order
- list_items — Lists all items in the customer cart.
- create_refund — Creates a refund for a paid order.
    order_id: string! — identifier of the order
    amount: number! — refund amount
- send_message — Sends a text message to the customer.
    text: string! — message body
"""

HISTORY = """⟦USER⟧
Can you check my order ORD-1?
⟦ASSISTANT⟧
→ TOOL_CALL check_status: {"order_id": "ORD-1"}
← TOOL_RESPONSE check_status: {"status": "shipped"}
⟦ASSISTANT⟧
Your order has shipped.
⟦USER⟧
Now I want a refund and a message.
"""


def build_case(case_id: str, policy: str, response: str) -> object:
    prompt = f"⟦SYSTEM⟧\n{policy}\n\n{CATALOG}\n{HISTORY}"
    return parse_case_v02(case_id, prompt, response)


def reasons(ctx) -> list:
    return [h.reason for h in ctx.structural_hits]


def suspicion_kinds(ctx) -> list:
    return [s.kind for s in ctx.suspicions]


def test_ce1_one_call_clause_does_not_forbid_text() -> None:
    """CE1: 'You should only make one tool call at a time.' + 1 call +
    'I will check the record.' — the rule limits the NUMBER of calls; it
    does not forbid accompanying text. NO ERROR from R2."""
    ctx = build_case(
        "ce1",
        "You should only make one tool call at a time.",
        "I will check the record.\n→ TOOL_CALL check_status: "
        "{\"order_id\": \"ORD-1\"}")
    r = reasons(ctx)
    assert "policy_text_and_call_violation" not in r, f"CE1 FAIL: {r}"
    assert "policy_one_call_violation" not in r, f"CE1 FAIL: {r}"
    # the mix is preserved as a NEUTRAL suspicion for the judge
    assert "policy_mixed_text_and_call_possible" in suspicion_kinds(ctx), \
        "CE1: expected neutral suspicion for the text+call mix"
    print("CE1 PASS: no hit; neutral suspicion emitted")


def test_ce2_negated_restriction_two_calls() -> None:
    """CE2: 'You are not restricted to one tool call at a time.' + 2 calls
    — regex hit on the fragment does not confirm a prohibition."""
    ctx = build_case(
        "ce2",
        "You are not restricted to one tool call at a time.",
        "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}\n"
        "→ TOOL_CALL list_items: {}")
    r = reasons(ctx)
    assert "policy_one_call_violation" not in r, f"CE2 FAIL: {r}"
    assert "policy_text_and_call_violation" not in r, f"CE2 FAIL: {r}"
    print("CE2 PASS: negated restriction never fires")


def test_ce3_read_only_exception_not_lost() -> None:
    """CE3: 'Only make one tool call at a time. You may make two read-only
    calls together.' + 2 READ-ONLY calls — the exception must not be
    lost: no confirmed hit, a suspicion carries the exception to the
    judge."""
    ctx = build_case(
        "ce3",
        "Only make one tool call at a time. You may make two read-only "
        "calls together.",
        "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}\n"
        "→ TOOL_CALL list_items: {}")
    r = reasons(ctx)
    assert "policy_one_call_violation" not in r, f"CE3 FAIL: {r}"
    kinds = suspicion_kinds(ctx)
    assert "policy_one_call_exception_applies" in kinds, \
        f"CE3: exception not carried to judge: {kinds}"
    print("CE3 PASS: exception applies -> suspicion, no confirmed hit")


def test_ce3b_write_calls_outside_read_only_exception() -> None:
    """CE3b: same policy, but the two calls include WRITE tools — the
    exception is explicitly scoped to read-only calls, so the restriction
    stands for these calls (confirmed, both clauses quoted)."""
    ctx = build_case(
        "ce3b",
        "Only make one tool call at a time. You may make two read-only "
        "calls together.",
        "→ TOOL_CALL create_refund: {\"order_id\": \"ORD-1\", "
        "\"amount\": 10.0}\n→ TOOL_CALL send_message: "
        "{\"text\": \"refunded\"}")
    r = reasons(ctx)
    assert "policy_one_call_violation" in r, f"CE3b FAIL: {r}"
    hit = [h for h in ctx.structural_hits
           if h.reason == "policy_one_call_violation"][0]
    assert "read-only" in hit.basis, \
        "CE3b: the exception clause must be quoted in the basis"
    print("CE3b PASS: write calls outside exception scope -> confirmed hit")


def test_ce4_text_call_prohibition_is_separate_requirement() -> None:
    """CE4: an explicit separate prohibition of combining text and a call
    is checked as its own requirement with its own quote."""
    ctx = build_case(
        "ce4",
        "Only make one tool call at a time. Do not combine text and tool "
        "calls in the same response.",
        "I will check the record.\n→ TOOL_CALL check_status: "
        "{\"order_id\": \"ORD-1\"}")
    r = reasons(ctx)
    assert "policy_text_and_call_violation" in r, f"CE4 FAIL: {r}"
    hit = [h for h in ctx.structural_hits
           if h.reason == "policy_text_and_call_violation"][0]
    # its OWN quote — the text+call clause, not the one-call clause
    assert "Do not combine text and tool calls" in hit.basis, \
        "CE4: the text+call prohibition clause must be quoted verbatim"
    # and the one-call restriction is NOT the trigger here (1 call only)
    assert "policy_one_call_violation" not in r, \
        "CE4: one call cannot trigger the count restriction"
    print("CE4 PASS: separate requirement with its own quote")


def test_ce4b_call_only_no_text() -> None:
    """CE4b: text+call prohibition present, but the response is a pure
    tool call — no hit."""
    ctx = build_case(
        "ce4b",
        "Do not combine text and tool calls in the same response.",
        "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}")
    r = reasons(ctx)
    assert "policy_text_and_call_violation" not in r, f"CE4b FAIL: {r}"
    print("CE4b PASS: pure call, no text -> no hit")


def test_t5_unambiguous_two_calls_still_confirmed() -> None:
    """Positive control: bare restriction, no exception, two calls — the
    old V0.1 R1 behavior is preserved for the unambiguous case."""
    ctx = build_case(
        "t5",
        "You should only make one tool call at a time.",
        "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}\n"
        "→ TOOL_CALL list_items: {}")
    r = reasons(ctx)
    assert "policy_one_call_violation" in r, f"T5 FAIL: {r}"
    print("T5 PASS: unambiguous violation still confirmed")


def test_t6_permission_wordings() -> None:
    """T6: other permission wordings must not be read as restrictions."""
    for policy in (
        "There is no restriction on the number of tool calls you can make.",
        "You may make multiple tool calls in a single response.",
        "You can make more than one tool call at once.",
    ):
        ctx = build_case("t6", policy,
                         "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}\n"
                         "→ TOOL_CALL list_items: {}")
        r = reasons(ctx)
        assert "policy_one_call_violation" not in r, \
            f"T6 FAIL for policy: {policy!r} -> {r}"
    print("T6 PASS: permission wordings never fire")


def test_t7_either_or_never_both() -> None:
    """T7: 'either text or a tool call, never both' is an explicit
    text+call prohibition (CE4 class)."""
    ctx = build_case(
        "t7",
        "Respond with either text or a tool call, never both.",
        "Checking now.\n→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}")
    r = reasons(ctx)
    assert "policy_text_and_call_violation" in r, f"T7 FAIL: {r}"
    print("T7 PASS: either/or-never-both recognized as separate prohibition")


def test_analyze_policy_units() -> None:
    """Unit checks of the clause classifier itself."""
    p1 = analyze_policy(
        "You should only make one tool call at a time.")
    assert p1.count_restriction is not None and not p1.exceptions
    p2 = analyze_policy(
        "You are not restricted to one tool call at a time.")
    assert p2.restriction_negated or p2.count_restriction is None
    p3 = analyze_policy(
        "Only make one tool call at a time. You may make two read-only "
        "calls together.")
    assert p3.count_restriction is not None
    assert len(p3.exceptions) == 1 and p3.exception_read_only_scoped
    p4 = analyze_policy(
        "Only make one tool call at a time. Do not combine text and tool "
        "calls in the same response.")
    assert p4.count_restriction is not None
    assert len(p4.text_call_prohibitions) == 1
    p5 = analyze_policy(
        "Tool calls must be sent without any accompanying text.")
    assert len(p5.text_call_prohibitions) == 1
    p6 = analyze_policy(
        "Be polite with the customer. Check the order before refunding.")
    assert p6.count_restriction is None and not p6.text_call_prohibitions
    print("analyze_policy units PASS")


def main() -> int:
    tests = [
        test_ce1_one_call_clause_does_not_forbid_text,
        test_ce2_negated_restriction_two_calls,
        test_ce3_read_only_exception_not_lost,
        test_ce3b_write_calls_outside_read_only_exception,
        test_ce4_text_call_prohibition_is_separate_requirement,
        test_ce4b_call_only_no_text,
        test_t5_unambiguous_two_calls_still_confirmed,
        test_t6_permission_wordings,
        test_t7_either_or_never_both,
        test_analyze_policy_units,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAILED {t.__name__}: {e}")
    print(f"\n{'='*60}\n{len(tests)-failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

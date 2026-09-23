#!/usr/bin/env python3
"""SEARCH_23 §2.3: regression tests for the v1 evidence-controller defects.

Directive §2.3 demands tests for exactly these failure modes:
  T1 exact quote + wrong semantic inference      (must NOT refute)
  T2 one ground refuted, second violation left   (case must stay 1)
  T3 ambiguous entity binding                    (AMBIGUOUS, no flip)
  T4 incomplete history / missing observation    (NOT_FOUND != SAFE, no flip)
  T5 missed exception (counter-hypothesis open)  (no 1->0 flip)

Run:  python experiments/searh_23/ev_controller_regression.py   (exit 0 = all pass)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_status import (  # noqa: E402
    AMBIGUOUS, NOT_FOUND, OBSERVED_STRUCTURED, SEMANTICALLY_SUPPORTED,
    SPAN_ANCHORED, SUSPICION_REFUTED, SUSPICION_SUPPORTED, UNKNOWN,
    EvidenceControllerV2, EvidenceItem, Suspicion, entity_binding, span_anchor)

POLICY = (
    "Refund Policy: The agent must verify the customer's identity before "
    "processing any refund. Refunds over $500 require manager approval, "
    "unless the customer has gold status. Refunds are only possible within "
    "30 days of purchase. Flight changes booked less than 24 hours before "
    "departure require supervisor confirmation."
)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def t1_quote_exists_inference_wrong():
    """v1 bug: VERIFIED_BY_SPAN flipped 1->0 whenever deciding words existed.
    Here the quote exists AND is real policy, but the NL answer draws a
    conclusion about a DIFFERENT order — must stay unverified."""
    print("\n[T1] exact quote, wrong inference")
    ctl = EvidenceControllerV2()
    # NL answer: real deciding words, wrong entity conclusion
    answer = {
        "answer": "The response is compliant: manager approval for order 10542 "
                  "was already given, so no violation.",
        "deciding_words": "Refunds over $500 require manager approval",
    }
    item = ctl.validate_nl(answer, POLICY, "does approval exist for the refund?")
    check("deciding words anchored in policy",
          item.status == SPAN_ANCHORED, item.status)
    # suspicion is about ANOTHER order
    s = Suspicion("S1", "agent processed a $700 refund for order 10999",
                  scope={"entity": "order 10999"})
    s.disposition = ctl.disposition(s, [item])
    check("span-only evidence never refutes", s.disposition != SUSPICION_REFUTED,
          s.disposition)
    v = ctl.case_verdict([s], control_label=1, counter_hypothesis_clear=True)
    check("case label unchanged (1)", v["label"] == 1 and v["flip"] is None,
          v["flip"] or "no flip")


def t2_one_ground_refuted_second_violation():
    """Refuting ONE suspicion must not clear the case when a second, verified
    violation remains."""
    print("\n[T2] one ground refuted, second violation remains")
    ctl = EvidenceControllerV2()
    s1 = Suspicion("S1", "agent claimed approval exists", scope={"entity": "order 1"})
    s1.disposition = SUSPICION_REFUTED  # verified refutation of THIS ground
    s2 = Suspicion("S2", "agent reported success, tool result was failed",
                   scope={"entity": "order 1"})
    s2.disposition = SUSPICION_SUPPORTED  # mechanical contradiction observed
    v = ctl.case_verdict([s1, s2], control_label=1, counter_hypothesis_clear=False)
    check("case stays 1 with a supported suspicion", v["label"] == 1,
          v["flip"] or "no flip")
    v0 = ctl.case_verdict([s1, s2], control_label=0, counter_hypothesis_clear=False)
    check("0->1 flip fires on supported suspicion", v0["label"] == 1,
          v0["flip"] or "no flip")


def t3_ambiguous_entity_binding():
    """Two observed candidates match the entity name: binding is AMBIGUOUS,
    never a silent pick."""
    print("\n[T3] ambiguous entity binding")
    cands = [{"id": "ORD-100", "value": "order 100 refund approved"},
             {"id": "ORD-100-b", "value": "order 100 baggage claim"}]
    b = entity_binding("order 100", cands)
    check("binding is AMBIGUOUS", b["status"] == AMBIGUOUS, b["status"])
    item = EvidenceItem(tool="graph_query", query="order 100", status=AMBIGUOUS,
                        method="binding_check")
    s = Suspicion("S1", "order 100 status", scope={"entity": "order 100"})
    s.disposition = EvidenceControllerV2().disposition(s, [item])
    check("ambiguous disposition, not supported/refuted",
          s.disposition == AMBIGUOUS, s.disposition)
    v = EvidenceControllerV2().case_verdict([s], control_label=1,
                                            counter_hypothesis_clear=True)
    check("no flip on ambiguous binding", v["label"] == 1, v["flip"] or "no flip")


def t4_incomplete_history():
    """A premise that is simply not observed is NOT_FOUND — it is not proof of
    compliance (v1 had no such guarantee: unknown premises could pass)."""
    print("\n[T4] incomplete history / missing observation")
    ctl = EvidenceControllerV2()
    res = {"verdict": "unknown", "premises": [{"fact": "approval observed",
                                               "status": "not_observed"}]}
    # premise_check with unknown premises -> NOT_FOUND (v1: UNKNOWN_PREMISES
    # but the aggregator could still see 'safe')
    item = EvidenceItem(tool="premise_check", query="approval",
                        status=NOT_FOUND, method="clingo_premise_scan",
                        limitations=["premise not observable in history"])
    s = Suspicion("S1", "refund without approval", scope={})
    s.disposition = ctl.disposition(s, [item])
    check("NOT_FOUND disposition", s.disposition == NOT_FOUND, s.disposition)
    v = ctl.case_verdict([s], control_label=1, counter_hypothesis_clear=True)
    check("NOT_FOUND never flips 1->0", v["label"] == 1, v["flip"] or "no flip")


def t5_missed_exception():
    """Both primary channels missed the same UNLESS exception. The counter
    hypothesis (missed-violation scan) must stay open: no 1->0 flip even if
    every *surfaced* suspicion was refuted."""
    print("\n[T5] missed exception keeps counter-hypothesis open")
    ctl = EvidenceControllerV2()
    s1 = Suspicion("S1", "refund without manager approval", scope={})
    s1.disposition = SUSPICION_REFUTED
    # counter-hypothesis scan found an UNCOVERED exception span in policy:
    exc = span_anchor("unless the customer has gold status", POLICY)
    check("exception span exists in policy", exc["anchored"])
    # but no channel surfaced the gold-status fact for this customer:
    counter_clear = False  # cannot clear what was never checked
    v = ctl.case_verdict([s1], control_label=1,
                         counter_hypothesis_clear=counter_clear)
    check("case stays 1 while counter-hypothesis open", v["label"] == 1,
          v["flip"] or "no flip")
    v2 = ctl.case_verdict([s1], control_label=1, counter_hypothesis_clear=True)
    check("case flips only when counter verified clear", v2["label"] == 0, v2["flip"])


def t6_semantic_check_is_probabilistic():
    """Extra guard: a semantic_check verdict alone (even 'refutes') never
    reaches SUSPICION_REFUTED — it is recorded, not conflated."""
    print("\n[T6] semantic check stays probabilistic")
    ctl = EvidenceControllerV2()
    sem = ctl.semantic_support("approval exists", "manager approval", "refutes")
    check("semantic item recorded as SEMANTICALLY_SUPPORTED (signal)",
          sem.status == SEMANTICALLY_SUPPORTED, sem.status)
    s = Suspicion("S1", "refund without approval", scope={})
    s.disposition = ctl.disposition(s, [sem])
    check("semantic-only evidence does not refute the suspicion",
          s.disposition != SUSPICION_REFUTED, s.disposition)


def main() -> int:
    print("SEARCH_23 §2.3 evidence-controller v2 regression tests")
    t1_quote_exists_inference_wrong()
    t2_one_ground_refuted_second_violation()
    t3_ambiguous_entity_binding()
    t4_incomplete_history()
    t5_missed_exception()
    t6_semantic_check_is_probabilistic()
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} passed, {n_fail} failed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name}: {detail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

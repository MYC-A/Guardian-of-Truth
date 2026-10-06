# Verification V4 — architecture

Control `guard_adm2` (A) decides first; an A ERROR is final. Only when A ≠ ERROR do the mechanisms run, each on a
deterministic trigger (no model, no gold). Every candidate is a structured accusation
`{origin, target_id, requirement, reason, policy_source_ids, evidence_source_ids, code_proven, relation_by_code}`
and passes the V3 Q2 narrow verifier unless an arm explicitly says otherwise. Arms are projections of one record
(`v4.decide_v4`), so all arms within a repetition are paired.

| module | role | model calls |
|---|---|---|
| `verification/proof.py` | typed proof executor: closed op set (EQ…NOT_MEMBER_OF, SUM_COMPARE_*, date ops, LATEST_VALUE_EQ, MEMBER_OF), roles, types; every leaf `{source_id, verbatim quote, value, type}` verified on its own source (Q2 + numbers grounded, or JSON leaf-by-leaf); value must occur in the quote; empty JSON list term = 0; any defect → UNRESOLVED | 0 |
| `verification/df4.py` | DF-only. Code extracts claims (dates, weekdays, money, durations); code self-checks: WEEKDAY_ADJACENT, INLINE_ARITHMETIC (`a×b+c = d`, `d: (a−b)×c`), RANGE_NIGHTS. Remaining claims → one binder call (operation from a closed enum + operand quotes); operand values parsed by code; guards CLAIM_VALUE_IN_TOOL_RESULT, CLAIM_IS_EXPRESSION_OPERAND, INCLUSIVE_COUNT_AMBIGUOUS, OPERAND_FROM_CURRENT_MOVE; `now` fallback `qf_now` from the full system prompt | 0–1 |
| `verification/ems.py` | Ems = E1 (V3 requirement discovery, byte-identical) → E2 proof plan per requirement (PROOF / SEMANTIC / NOT_APPLICABLE) → executor. Gates: code VIOLATED + model SATISFIED → UNRESOLVED; polarity check (upper-limit wording with GT/GE etc.) → UNRESOLVED; SEMANTIC VIOLATED only with every evidence piece verified. Trigger T_multi ∪ T_quant (+ ≤3 full-system limit spans `qf1..`) | 2 |
| `verification/alltarget.py` | AT: one call returns one item per current target; code requires exact coverage; candidate = first admitted ERROR in move order | 1 |
| `verification/second.py` (V3) | CTRL: ordinary skeptical re-review on the same T_multi rows | 1 |
| `verification/confirm.py` (V3) | CB shadow (user-actor affirmation) | 1 per trigger |
| `verification/verifier.py` | Q2 narrow verifier; V4 adds `multi_piece` evidence (pieces from different sources each verified, number-strict) and DF4 own-requirement policy quote | 1 (+1 invalid-JSON retry) |
| `verification/v4.py` | `run_v4` (records), `decide_v4` (arms A, A_DF, A_DF_mech, A_Ems, A_Ems_mech, A_AT, A_CTRL, A_CB_shadow, V4, V4_mechanical, V4_mech_strict, *_raw) | — |
| `experiments/verification_v4/score.py` | judge (unchanged integrated-v1 cause judge), report (cc gains, new FP, strata, later-call recall, verifier stats, triggers, AT coverage, calls/tokens, audit invariants), flips | judge only |
| `experiments/verification_v4/external/render.py` | tau2 → Guardian markup renderer (catalog/policy byte-identical to valid46 for all 35 airline/retail/telecom rows) | 0 |

Arm definitions: `V4` = A ∨ DF4 ∨ Ems ∨ AT (all verified). `V4_mechanical` = code-proven DF4/Ems candidates
admitted without verifier. `V4_mech_strict` = only DF4 self-check candidates (relation fixed entirely by code, no
model binding) skip the verifier; everything else verified.

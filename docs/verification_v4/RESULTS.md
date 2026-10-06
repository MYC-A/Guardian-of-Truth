# Verification V4 — results

## 0. Incident: workspace rollback (2026-10-06)
During dev the sandbox `/data` was restored from an older backup: all uncommitted V4 code, the V4 Mistral cache
(~120 mechanism replies) and dev records were lost; commit 1 (`7a1999b2`) survived on GitHub. The code was restored
by replaying the exact edit commands from the session log (proof, df4, ems, alltarget, v4, verifier, score, render,
tests; unit tests and valid46 catalog byte-identity re-checked), a backup branch `backup/v4-wip-20261006` was pushed,
and the dev regression was re-run. Re-executed mechanism calls (temperature 0) did **not** reproduce exactly:
A replies are cached and identical, but e.g. LB3 r1 TL3e (DF) and AS7n (AT FP) changed and LB2 G3n (AT FP) / T5n (DF FP)
appeared. This is direct evidence of run-to-run variance of the mechanism calls — the reason the external evaluation
uses 3 repetitions and per-rep decision rules.

## 1. Baseline reproduction
See PROTOCOL §1 / `outputs/verification_v4/baseline_repro.json` (reproduced exactly offline).

## 2. Dev log (regression sets only; no adoption claim)
* **Iteration 1** (`_v4dev1`): bugs fixed — binder operand role naming (map roles by quoted type: TL3e), empty JSON
  list sum term = 0, verifier multi-piece evidence (BK3e AT raw ERROR killed by single-quote verifier), number-strict
  leaf quotes (Q2 word tolerance must never change a number).
* **Iteration 2** (`_v4dev2`): copied-value guard (claim value literally in a tool result → not derived; CL3n FP),
  Ems contradiction gate (code VIOLATED + model SATISFIED → UNRESOLVED) and polarity check (K6n, T3n, IN3n
  mechanical FPs), verifier DF4 own-requirement policy quote (H5e/K3e correct DF candidates downgraded), inline
  `d: (expr)` + expression-operand guard (CR5n FP), strict mechanical arm `V4_mech_strict`.
* **Iteration 3** (`_v4dev3`, after the rollback re-run): forward-only date operations (NEXT_BUSINESS_DAY, ADD_*)
  cannot explain a claimed date earlier than their input → UNVERIFIED (T5n FP: deadline before event bound as
  next-business-day).

Final dev table (`_v4dev3`; cc = new cause-correct TP vs A; FP = new FP vs A):

| set/rep | A TP/FP F1 | A_DF | A_Ems | A_AT | A_CTRL | V4 | V4_mech | V4_mech_strict | CB shadow | calls/row |
|---|---|---|---|---|---|---|---|---|---|---|
| valid46 r1 | 15/3 0.732 | +0cc/0FP | +0cc/0FP | +0cc/0FP | +0cc/0FP | +0cc/0FP | +0cc/0FP | +0cc/0FP | +0cc/0FP | 1.24 |
| lb_long r1 | 20/3 0.784 | +0cc/0FP | +1cc/0FP | +1cc/0FP | +0cc/0FP | +2cc/0FP | +2cc/0FP | +2cc/0FP | +2cc/0FP | 2.53 |
| lb2_long r1 | 19/1 0.884 | +1cc/0FP | +0cc/0FP | +0cc/1FP | +0cc/0FP | +1cc/1FP | +2cc/2FP | +1cc/1FP | +1cc/0FP | 2.28 |
| lb3_long r1 | 23/7 0.793 | +1cc/0FP | +0cc/0FP | +1cc/0FP | +0cc/0FP | +2cc/0FP | +2cc/0FP | +2cc/0FP | +1cc/0FP | 1.8 |
| lb3_long r2 | 23/4 0.836 | +3cc/0FP | +1cc/0FP | +1cc/1FP | +0cc/0FP | +4cc/1FP | +4cc/1FP | +4cc/1FP | +0cc/0FP | 1.93 |

Residual FPs on dev: AS7n (LB3 r2, AT semantic hallucination, verifier SUPPORTED), G3n (LB2, AT: "at most 4 future
sessions" claimed violated with 1+2 sessions; verifier SUPPORTED), H5n (only `V4_mechanical`, DF binder). These are not
fixed (no generic rule without overfitting); they are the expected failure mode of AT/verifier.

## 3. Residual matrix (dev)
| case | previous failure | V4 mechanism | candidate? | proof executable? | admitted? | cause correct? |
|---|---|---|---|---|---|---|
| CL3e (LB3) | weekday next to date wrong | DF4 WEEKDAY_ADJACENT | yes | code-only | yes (both reps) | yes |
| TL3e (LB3) | business-day date | DF4 binder ADD_BUSINESS_DAYS | r2 yes, r1 no | yes | r2 | yes |
| AS3e (LB3) | arithmetic in prose | DF4 | r2 yes | yes | r2 | yes |
| BK3e (LB3) | cumulative daily limit over 2 calls | AT (r1, r2), Ems (r2) | yes | Ems: SUM_COMPARE_LE | yes | yes |
| BK6e (LB3) | — | none | no | — | — | — |
| CL1e (LB3) | confirmation | CB shadow (r1) | r1 | — | r1 | yes |
| G3e (LB2) | later call | AT | not in final run | — | — | — |
| T6e (LB2) | confirmation | CB shadow | yes | — | yes | yes |
| H5e (LB2) | price × nights | DF4 | yes | yes | yes | yes |
| K3e (LB2) | derived value | DF4 binder | yes | yes | only mechanical | yes |
| CR1e / CR3e (LB1) | limit / later call | Ems / AT | yes | Ems proof | yes | yes |
| UN1e (LB1) | later call | CTRL only (cause≠) | — | — | — | no |
| IN4e, UN4e (LB1) | confirmation | CB shadow | yes | — | yes | yes |
Closed tool / stale state / failed receipt / wrong entity: no dev case newly caught by V4 (A already catches the
closed-tool and failed-receipt cases; stale state/wrong entity are reported as not covered).

Post-processing losses found and fixed on dev: BK3e (AT ERROR killed by single-quote verifier), H5e/K3e (DF correct,
policy-quote downgrade), TL3e (binder operand naming).

## 4. External evaluation
(filled after commit 4/5)

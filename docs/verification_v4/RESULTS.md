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

## 4. External evaluation (`ext_tau2`, gold v1 — **WITHDRAWN**, see §4b; kept for the record)

### 4a. v1 numbers (`ext_tau2`, 70 rows: 35 ERROR / 35 NO_ERROR; frozen in commit 4, see EXTERNAL_DATA.md)

3 primary reps, identical settings, paired; code frozen at commit 3 (no change after). Raw reports:
`outputs/verification_v4/external/tau2/reports/`. cc = new cause-correct TP vs A; binary = new TP (any cause) / new FP.

| rep | A tp/fp F1 (cc) | A_DF | A_Ems | A_AT | A_CTRL | V4 (= V4_mech = V4_mech_strict) | calls/row |
|---|---|---|---|---|---|---|---|
| 1 | 18/12 .554 (2) | 0 | 0 cc, +0/+1FP | 0 cc, +2/+5FP | 0 cc, +0/+3FP | 0 cc, +2/+5FP, F1 .556 | 1.76 |
| 2 | 19/13 .567 (3) | 0 | 0 cc, +1/0FP | 0 cc, +2/+4FP | 0 cc, +1/+1FP | 0 cc, +2/+4FP, F1 .575 | 1.81 |
| 3 | 18/13 .545 (3) | 0 | 0 cc, 0/+1FP | 0 cc, +4/+4FP | 0 cc, 0/+5FP | 0 cc, +4/+4FP, F1 .595 | 1.93 |

* Triggers: T_multi fired on 10/10/11 non-base-ERROR rows (2–4 positives), T_quant on 1–3 negatives, **T_calc and DF never
  fired** (tau2 moves are single tool calls or pure prose, no stated quantities to recompute).
* All-target: complete coverage 10–11 rows; binary later-call recall 9/9 vs A 6–7/9, but every AT gain is judged
  cause≠ and costs 4–5 new FP per rep (FP mostly policy-boilerplate accusations on correct gold writes: ext_ret_029, ext_tel_047,
  ext_ret_022 recurring).
* Verifier: rejected 0–1 true (cause≠) and 0–2 false candidates per rep; it never changed a code-proven candidate, so V4,
  V4_mechanical and V4_mech_strict are identical on every row.
* Baseline instability: 17/70 rows flip A's decision across reps (16 "different evidence, different decision", 1 "different
  target selection"); several AT/CTRL FPs/gains are rep-specific.
* Cause-correct metric caveat: A itself is cause-correct on only 2–3 of 18–19 TP; gold causes are generated from the oracle
  diff ("not part of the correct resolution"), so the judge is conservative here. The verdicts below do not depend on it:
  even counted binarily, V4/AT net gain is +2−5, +2−4, +4−4.
* Cost: ≈385 Guardian calls over 3 reps (≈9–10k tokens/row) + ≈70 judge calls.

### Pre-registered verdicts (§5, §7)
| rule | evidence | verdict |
|---|---|---|
| Combined V4 | 0 cc in every rep (need ≥3), new FP 5/4/4 (need ≤1) | **REJECT** |
| DF-only | DF never triggered on the external set (no eligible case) | **INSUFFICIENT EVIDENCE** (stays shadow; 0 FP) |
| All-target | T_multi net cc gain AT −5/−4/−4 vs CTRL −3/−1/−5 → AT > CTRL in 1/3 reps; later-call recall binary only | **schema gives no mechanism** (not useful) |
| Multi-source proof | no compositional/calc positive triggered; Ems: 0 cc, 1 cause≠ gain, FP in reps 1 and 3 | **INSUFFICIENT EVIDENCE** (no eligible case); no positive signal |
| §5 verifier criterion | verifier never rejected a code-proven candidate | not met → `V4_verified` stays primary (moot) |
| ≥25 positives | 35 | satisfied |

Default stays **guard_adm2** (A). See FINAL_DECISION.md.

**These v1 verdicts are withdrawn (Amendment 2):** gold v1 equated tau2 task success with Guardian compliance — all 15
`multi_read` NO_ERROR rows violate "one tool call at a time", 4 `gold_write` rows mix prose and a tool call; causes were tau2
action diffs. Several "V4 FP" above were correct detections.

## 4b. Rescoring on gold v2 (Amendment 2; stored outputs, no new Guardian calls; **exploratory, unblinded**)

Gold v2 (`ext_tau2v2`): 68 rows = 52 ERROR (19 format-only F1/F2, 33 with a substantive cause) / 16 NO_ERROR; 2 UNCERTAIN excluded.
Cause judge re-run once per (accusation, acceptable cause): 184 jobs (+ retries; 3 unjudged → counted not SAME).
Raw: `outputs/verification_v4/external/ext_tau2v2/RESCORE_v2.json`, logs in `.../tau2v2/reports/`.

| rep | A tp/fp F1 (cc) | V4 = A_AT tp/fp F1 | V4 new TP / new FP | V4 new cc-TP | A_CTRL new TP / cc / FP | A_Ems new TP / cc | later-call A→V4 |
|---|---|---|---|---|---|---|---|
| 1 | 29/1 .707 (5) | 36/1 .809 | +7 / 0 | 2 | +3 / 1 / 0 | +1 / 1 | 7/9 → 9/9 |
| 2 | 31/1 .738 (6) | 37/1 .822 | +6 / 0 | 1 | +2 / 0 / 0 | +1 / 0 | 7/9 → 9/9 |
| 3 | 30/1 .723 (3) | 38/1 .835 | +8 / 0 | 0 | +5 / 2 / 0 | +1 / 0 | 6/9 → 9/9 |

* Strata: format-only rows — V4 +5/+4/+4 TP (A catches 11–13 of 19); substantive rows — V4 +2/+2/+4 TP. Strict variant
  (`ext_tau2v2_strict`, 65 rows without oracle-only causes): identical gains, F1 .837/.851/.851 vs A .734/.765/.734.
* **Most V4 gains are right row, wrong reason.** Manual reading of all 21 gain accusations: correct cause in ≈3/2/1 per rep
  (judge SAME on 4; PARTIAL on 3 accusations that literally cite "one tool call at a time" — judge noise); the rest accuse
  generic confirmation / "one user per conversation" / "made-up information" boilerplate on multi-call moves, or claim missing
  confirmation that is present (ext_air_043, ext_ret_019, ext_ret_041).
* DF never triggered; Ems gains are SEMANTIC-mode confirmation claims, no compositional case. Verifier: V4 = V4_mechanical = strict.
* Only 16 negatives: A FP = ext_tel_015 (r1, borderline: total price not restated) / ext_ret_046 (r2, r3, false "confirmation must
  be in the tool call"); V4 adds no FP on negatives.

### §7 applied to gold v2 (exploratory — cannot ADOPT, Amendment 2 §4)
| rule | evidence | outcome |
|---|---|---|
| Combined V4 | new cc 2/1/0 (≤3/2/1 counting PARTIAL) — need ≥3 each rep; FP 0; T_multi V4−CTRL cc +1/+1/−2 | **not met** |
| DF-only | never triggered | **INSUFFICIENT EVIDENCE** (external τ² says nothing about DF transfer) |
| All-target | T_multi net cc AT 2/1/0 vs CTRL 1/0/2 → AT > CTRL in 2/3 reps; later-call recall 9/9 > 6–7/9 | **formally met, by one accusation per rep** → candidate for a blinded external test, not adoption |
| Multi-source proof | no compositional positive | **NOT TESTED externally** |
| §5 verifier | never rejected a code-proven candidate | not met; verified stays |

Observation: 19/52 errors are mechanical format violations that a deterministic check (calls ≥ 2, prose + call, when the policy
states the rule) would catch with no model call; A and V4 miss several of them or catch them for the wrong reason.

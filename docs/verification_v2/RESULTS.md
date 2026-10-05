# Verification v2 — results

Model `ministral-14b-2512` (Mistral) for every arm and the cause judge; 1 repetition; temperature 0.
Calls: 793 reviewer attempts (761 × 200, 32 × 429 retried) + 136 judge calls (cap 1400).
"same" = cause-correct TP (judge SAME vs gold cause, plus mechanical guard proofs). Reports: `outputs/verification_v2/reports/*.json`.

## 0. Amendment 4 — architecture V3 on the fresh LB3-long (56 cases, 28 ERROR; frozen 2be50fd4, code frozen a2afcc1f)
Held-out, run once with frozen code, 2 repetitions (attempt 0/1). Gains / new FP are vs `A_adm2` on the same rows and rep;
cause-correct = judge SAME (or mechanical guard). Reports: `outputs/verification_v2/reports/lb3_long_rep{1,2}_v3.json`.

| arm | rep1 TP/FP, F1 | rep1 gain (cause-correct) / new FP | rep2 TP/FP, F1 | rep2 gain / new FP |
|---|---|---|---|---|
| A_adm2 (default) | 23/7, .793 | — | 23/4, .836 | — |
| + G_closed | 23/7 | 0 / 0 | 23/4 | 0 / 0 |
| + E (T_multi) | 23/7 | 0 / 0 | 23/4 | 0 / 0 |
| + DF (T_calc) | 24/7, .814 | 1 (BK6e) / 0 | 25/4, .877 | 2 (AS3e, BK6e) / 0 |
| + CB (T_confirm) | 24/7, .814 | 1 (CL1e) / 0 | 23/4 | 0 / 0 |
| **V3** | **25/7, .833** | **2 / 0** | **25/4, .877** | **2 / 0** |
| V3m (bypass verifier) | = V3 | 2 / 0 | = V3 | 2 / 0 |

Strata: general — V3 +1/0 (rep1), +0/0 (rep2); targeted (8 ERROR) — A_adm2 4 and 3 TP → V3 5 and 5.
**Pre-registered rules:** R1 (≥3 cause-correct gain per rep, ≤1 new FP) — **not met** (2 and 2; FP 0 and 0).
R2 — DF **useful** (3 gains over both reps, ≥1 per rep, 0 FP); CB not (1+0); E, G_closed not (0). R3 — no false
candidate reached the verifier on LB3 (4/4 true cause-correct kept), so the rejection half of §6 is untestable here.
R4 — V3m = V3, not preferred.
Still missed in both reps: TL3e, CL3e (prose_date: DF extraction did not follow the operand schema — weekday put in the
wrong field, "start counting next day" pre-applied by the model; code then refused = UNVERIFIED, no verdict) and BK3e
(later call in a multi-call move; E listed no violated requirement). Post-hoc observation only, not fixed on LB3.
Stability of the base: A_adm2 flips 5/56 rows between reps (FP 7 vs 4); V3 adds no FP in any of 5 runs
(dev: LB1-long +2/0, LB2-long +3/0, valid46 0/0; LB3 +2/0, +2/0). Cost: +0.6–0.7 calls/row on LB3 (DF 7–8, CB 19–22,
E 8 calls, verifier 2 per 56 rows).

## 1. Held-out LB2-long (47 cases, 23 ERROR; frozen in 9d170784, before E code) — primary for amendment 2

| arm | TP | FP | F1 | same | vs A: +TP / −TP / +FP | pairs |
|---|---|---|---|---|---|---|
| A (frozen A2, adm v1) | 17 | 1 | 0.829 | 12 | — | 16/23 |
| **A_adm2** | **19** | **1** | **0.884** | 12 | +2 / 0 / 0 | **18/23** |
| B / Bv | 19 / 18 | 2 / 1 | 0.864 / 0.857 | 14 / 13 | +2/0/+1 ; +1/0/0 | 17 / 17 |
| C / D | 18 / 17 | 1 / 1 | 0.857 / 0.829 | 12 / 12 | +1/0/0 ; 0/0/0 | 17 / 16 |
| E / Ev | 19 / 17 | 4 / 2 | 0.826 / 0.810 | 14 / 12 | +2/0/+3 ; 0/0/+1 | 16 / 15 |
| B′ / Bv′ | 19 / 19 | 2 / 1 | 0.864 / 0.884 | 12 / 12 | — | 17 / 18 |
| C′ / D′ | 19 / 19 | 1 / 1 | 0.884 / 0.884 | 12 / 12 | — | 18 / 18 |
| E′ / Ev′ | 20 / 19 | 4 / 2 | 0.851 / 0.864 | 13 / 12 | — | 17 / 17 |
| Av (shadow) | 15 | 1 | 0.769 | 11 | 0 / −2 / 0 | 14/23 |
| Av_strict | 10 | 0 | 0.606 | 7 | 0 / −7 / −1FP | 10/23 |

Pre-registered rules (PROTOCOL amendment 2):
1. **Admission v2: PASSED** (+2 TP, 0 FP, 0 TP lost) → adopted as default.
2. **E′: NOT supported** (vs A_adm2: +1 cause-correct TP, +3 FP). **Ev′: NOT supported** (+0, +1 FP).
3. **Counterfactual C′/D′: NOT supported** (+0 / +0 vs A_adm2; D: 0 gain vs A).
4. **Verifier: NOT useful on LB2** — rejects 3/4 false candidates (75%) but keeps only 1/4 true cause-correct candidates (25% < 70%).

Missed by every arm: chronology of confirmation (T6e), prose arithmetic on non-ISO dates (H5e: "10→15 October" nights), prose weekday/business day (K3e). E′ false positives were mostly incoherent items (reason says "does not exceed the limit", status VIOLATED) and "missing confirmation" on read-only moves.

## 2. LB1 (57 cases, 28 ERROR, frozen in d82b438b) — primary for the original protocol, development for E

| arm | LB1-long TP/FP F1 same | LB1-short TP/FP F1 same |
|---|---|---|
| A | 13/2 0.605 13 | 8/1 0.432 8 |
| **A_adm2** | **20/3 0.784 20** | **21/1 0.840 21** |
| B / Bv | 20/5 0.755 19 ; 18/3 0.735 18 | 22/2 0.846 21 ; 19/1 0.792 18 |
| C / D | 18/2 0.750 18 ; 17/2 0.723 17 | 21/2 0.824 21 ; 18/1 0.766 18 |
| B′ / Bv′ | 21/5 0.778 20 ; 20/3 0.784 20 | 23/2 0.868 22 ; 23/1 0.885 22 |
| C′ / D′ | 21/3 0.808 21 ; 20/3 0.784 20 | 24/2 0.889 24 ; 22/1 0.863 22 |
| E′ / Ev′ (dev, iteration 2) | 23/6 0.807 21 ; 21/4 0.792 21 | — |
| Av | 13/1 0.619 13 | 8/1 0.432 8 |

- Frozen §6 rule on LB1-long: D vs A +4 cause-correct TP with 0 new FP, but net 4 is not ≥2 above Bv (net 4 = 5 − 1) → **counterfactual direction not supported**. Most of the "gain" of every arm over A is the admission artefact: v1 rejected 20/57 long, 28/57 short (and 5/47 LB2, 2/46 valid46) replies only because tool-result evidence was labelled `system`/`unknown` instead of `assistant`.
- On the A_adm2 base the honest increments are small: C′ +1 TP/0 FP (LB1-long), +3 TP/+1 FP (short); D′ 0 (long), +1/0 (short).
- Verifier on LB1-long: false 3 → 2 rejected; true cause-correct 11 → 9 kept → "useful" there; it failed the same criterion on LB2 (above).

## 3. valid46 (development only; A2 was tuned there)
A 15/3 F1 0.732 = A_adm2 (no rejected replies in this rep). B/Bv 0.762; C 0.800 (+3 TP, +1 FP, but the 3 TP have causes judged DIFFERENT); D 0.714. Av removes 3 FP but loses 4 TP (0.647).
Offline admission-v2 replay of the 3 integrated-v1 reps: F1 0.732→0.732, 0.700→0.762, 0.611→0.611; rejected replies 2–4 → 0; no added FP. The new `guard_adm2` profile reproduces the replay end-to-end (asserted in `adm2_replay.py`).

## 4. Cost per row (LB2, escalated rows only for B/C/E)
A 1 call (~4.8k tokens). B +1, C +1, E +2 (~10k tokens), verifier +1 per candidate (~3k). Admission v2: 0 extra calls.

## 5. Limits (do not over-claim)
- Lockboxes are synthetic and written by the same author/process as the mechanisms (no external annotators); one pair per stratum, so per-family numbers are n=1–2.
- One repetition, one model family (Gemma unavailable: Ollama quota). Differences of 1–3 rows are within run-to-run noise seen in integrated v1 (valid46 F1 0.61–0.73 across reps).
- Cause-correctness uses an LLM judge from the same model family.
- E was iterated twice on LB1 (logged in amendment 2); LB2 was run once with the frozen code.
- Self-review instead of independent reviewers: no subagent tool was available in this environment; two separate review passes (code + protocol compliance) were done and found/fixed: scorer variable shadowing (`tag`) that wrote reports to wrong files, sign-test p-value not capped at 1, missing A_adm2 reasons in phase-1 records (now backfilled offline from the cached raw reply, asserted identical decision), quote-check false negatives (list markers, trailing punctuation).

See `AUDIT.md` (amendment 3) for the offline re-admission audit that revises the verifier and C/E conclusions.

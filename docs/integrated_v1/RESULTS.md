# Results: integrated v1

Sources: `outputs/integrated_v1/reports/report_final_v1.json` (scorer `experiments/integrated_v1/score.py`). The protocol and its amendments are in EXPERIMENT_PROTOCOL.md.

Conventions:
- Every run has 46 slots.
- Binary projection: ERROR→1. Everything else → 0: NO_ERROR, UNKNOWN, rejected admission, provider limit.
- **ccTP** = cause-correct TP: judge SAME+PARTIAL, plus guard-owned mechanical TPs. The judge is `ministral-14b-2512` (amendment 3; self-judging for Mistral reasons).
- **p** = two-sided sign test on per-row majority-over-reps correctness vs A1 (n=46; indicative only).

## 0. Zero-HTTP replay of the 12 archived sets (phase0)
- The repaired guard flags exactly the same rows as the pre-repair guard on valid46: 1 TP (`airline__23::t10`), 0 FP, no flag changes.
- Overlay on the archived U2_20k runs: F1 0.684/0.727/0.700, unchanged. The guard TP was already predicted there.
- FULL / U2_48k / FC2_48k gain +0.04–0.06 each.
- Archived Guardian OR Granite: 0.889 (context only; that is a different system).
- File: `outputs/integrated_v1/phase0_cache46/replay.json`.

## 1. valid46, Mistral `ministral-14b-2512` (3 reps per arm, fresh calls)
| Arm | F1 mean [min–max] | TP | FP | ccTP | calls/row | prompt tok/run | p vs A1 (better/worse) |
|---|---|---|---|---|---|---|---|
| **A1** corrected U2 direct | 0.659 [0.611–0.700] | 12.7 | 2.7 | 7.0 | 1.00 | 188k | — |
| **A2** + guard | **0.681** [0.611–0.732] | 13.3 | 2.7 | 8.0 | 1.00 | 188k | 1/0 (p=1.0) |
| A3 + relations (frozen) | 0.492 [0.389–0.571] | 8.7 | 3.7 | 6.0 | 1.00 | 209k | 4/7 (p=0.55), **worse** |
| A4 + controller (frozen) | 0.492 [0.389–0.571] | 8.7 | 3.7 | 6.0 | 1.03 | 216k | 4/7 (p=0.55), **worse** |
| A3g decisive-gated relations (post-hoc) | 0.686 [0.611–0.732] | 13.7 | 3.0 | 8.3 | 1.00 | 189k | 3/1 (p=0.63) |
| A4g + controller (post-hoc) | 0.686 [0.611–0.732] | 13.7 | 3.0 | 8.3 | 1.03 | 196k | 3/1 (p=0.63) |

- Rejected admissions: 2–5 per run in every arm; the main cause is EVIDENCE_REFERENCE_OR_ACTOR_INVALID.
- UNKNOWN: 0–1 per run.
- The controller fired on 1–2 of 46 rows and never changed a decision on valid46.
- Mean model latency is ≈ 8–10 s per call (4 parallel workers).
- Historical context: earlier U2_20k runs scored 0.684/0.727/0.700 with an older packer. Only 4/46 of those requests are hash-identical to today's, so the fresh A1 is the correct baseline.

## 2. valid46, Gemma `gemma4:31b` (Ollama, native json_object; 1 rep)
| Arm | Status | F1 | TP | FP | ccTP | notes |
|---|---|---|---|---|---|---|
| A1 | COMPLETE 46/46 | 0.611 | 11 | 2 | 2 | 3 technical nulls (2 rejected); 45/46 replies fenced and unwrapped; 4.5k prompt tok/row; ≈ 5.5 s/call |
| A2 | COMPLETE (overlay) | 0.611 | 11 | 2 | 3 | the guard TP was already an ERROR; ownership moves to the guard |
| A3/A4 | **PARTIAL 16/46** | n/a | | | | 30 slots `429 monthly usage limit` → reported, not imputed |
| Paired pilot (16 rows, 9 positives, both profiles executed) | | A1 = A2 = A3 = A4: TP 4, FP 0, F1 0.615 | | | | identical decisions; a pilot, not evidence |

- Gemma's TPs are mostly **wrong-cause**: 9 of 11 judged DIFFERENT.
- Gemma rep 2 and Gemma SYN-M1 were not executed (provider limit). AI Horde `google/gemma-4-31b` was smoke-tested once and truncated the output, so it was unusable (amendment 1).

## 3. SYN-M1 lockbox (authored, seen; Mistral, 3 reps)
| Arm | F1 mean [min–max] | TP | FP | ccTP | CALL_ARG_ID recall (17) | FACT_NUMBER recall (6) | p vs A1 |
|---|---|---|---|---|---|---|---|
| A1 | 0.768 [0.732–0.791] | 16.0 | 2.7 | 11.7 | 13.0 | 3.0 | — |
| A2 | 0.768 | 16.0 | 2.7 | 11.7 | 13.0 | 3.0 | 0/0 |
| A3 (frozen) | 0.725 [0.683–0.773] | 15.0 | 3.3 | 12.7 | 13.7 | 1.3 | 2/8 (p=0.11), worse |
| A4 (frozen) | 0.725 | 15.0 | 3.3 | 12.7 | 13.7 | 1.3 | 2/8 (p=0.11), worse |
| A3g (post-hoc) | 0.825 [0.818–0.837] | 18.0 | 2.7 | 14.3 | 15.0 | 3.0 | 2/0 (p=0.5) |
| A4g (post-hoc) | **0.833** [0.818–0.844] | 18.3 | 2.7 | 14.3 | 15.3 | 3.0 | 2/0 (p=0.5) |

- The controller fired on 2–4 of 46 rows and added 1 TP in one rep (A4g rep1).
- Caveats:
  - SYN-M1 operators overlap the decisive relations by construction (CALL_ARG_ID ↔ NOT_OBSERVED argument).
  - This suite was seen in the previous phase.
  - The gated variant was designed after the valid46 results.

## 4. Diagnosis
1. **Reassurance/dilution from confirmations.** In frozen A3, most changed rows had **no decisive fact**; they received only `OBSERVED_BEFORE_MOVE` confirmations. Several stable baseline detections went 3/3 → 0–1/3. Examples:
   - `airline__7::t6`, `airline__9::t6`, `telecom…t27`, `telecom…t15`: ERROR → NO_ERROR.
   - The reasons became "values are grounded, compliant".

   Gating to decisive-only facts removes this effect. On valid46, 40/46 requests become byte-identical to A1.
2. **Decisive facts help only where they match the actual violation.**
   - `retail__106::t3`: zip "3019" occurs only as a substring of the email. A3 says ERROR, but the reason given is authentication order (the judge marks it different).
   - `retail__48::t4`: an identical retry after an ERROR receipt. It was rejected at admission because the reviewer labelled the tool receipt's actor `system` (the known actor contract issue).
   - telecom `t10`: the repeated-call fact moves the cause away from the gold cause (unavailable tools).
3. **Controller.** The trigger is rare (UNKNOWN is rare, and decisive facts with NO_ERROR are rare), so it contributes almost nothing at ≈ +3–9% calls.
4. **Guard.** It gives +1 mechanically proven TP (`airline__23::t10`) and 0 FP in every scored run, valid46 and SYN-M1, both families. It costs 0 calls.
5. **Wrong-cause TPs remain large:** about 45% of Mistral A1 TPs and 82% of Gemma A1 TPs. Label-level F1 overstates verification quality.

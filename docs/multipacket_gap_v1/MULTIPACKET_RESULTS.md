# Multi-packet results (A, B, FULL, C, D)

The model is `ministral-14b-2512`, T=0, I4 contract. "calls" = reviewer calls per row, including the first pass. rcTP = reason-correct TPs (gpt-oss:120b judge, SAME+PARTIAL). Success rule (pre-registered): F1 higher than A **and** rcTP not lower **and** paired sign test p<0.1.

## 1. SYN-M1 final (46 cases, 3 repetitions; `reports/syn_m1_aggregate.json`)
| Arm | F1 mean [min–max] | TP | FP | rcTP | DIFF | calls | prompt tok/row | rows better/worse vs A (sign p) | success |
|---|---|---|---|---|---|---|---|---|---|
| **A** U2 20k | **0.789** [0.750–0.818] | 16.3 | 2.0 | 14.0 | 2.3 | 1.0 | 3.5k | — | — |
| B U2 48k | 0.729 [0.634–0.810] | 15.3 | 3.7 | 12.3 | 3.0 | 1.0 | 6.6k | 3/10 (p=0.09, **worse**) | no |
| FULL | 0.753 [0.667–0.829] | 15.3 | 2.3 | 13.3 | 2.0 | 1.0 | 13.4k | 4/8 (0.39) | no |
| CTRL (A twice + aggregator) | **0.819** [0.762–0.857] | 17.3 | 2.0 | **15.0** | 2.3 | 1.8 | 6.8k | 5/2 (0.45) | no (p) |
| CTRL any_error | 0.833 | 18.3 | 2.7 | n/j | | 1.8 | 6.8k | 5/2 (0.45) | no (p) |
| C1 parallel complementary | 0.759 [0.732–0.780] | 16.3 | 3.7 | 13.7 | 2.7 | 2.0 | 6.7k | 2/6 (0.29) | no |
| D1 sequential fixed | 0.770 [0.718–0.800] | 15.7 | 2.0 | 14.0 | 1.7 | 1.7 | 7.2k | 0/2 (0.5) | no |
| D2 sequential gap-directed | 0.757 [0.684–0.818] | 15.3 | 2.0 | 14.0 | 1.3 | 1.7 | 7.4k | 0/2 (0.5) | no |
| D1/D2 sticky | 0.789 | 16.3 | 2.0 | n/j | | 1.7 | 7.2k | 0/0 | no |
(G2_L and G4_S are in GAP_CONTROLLER_RESULTS.md. n/j = not judged.)

Strata (recall averaged over the 3 runs; `reports/syn_m1_strata.json`):
| Arm | FACT_NUMBER recall (6) | CALL_ARG_ID recall (17) | positives >20k (18) | FP rate on negatives |
|---|---|---|---|---|
| A | 0.39 | 0.82 | 0.69 | 0.087 |
| B | 0.50 | 0.73 | 0.63 | 0.159 |
| FULL | 0.50 | 0.73 | 0.63 | 0.101 |
| CTRL | 0.50 | 0.84 | 0.74 | 0.087 |
| C1 | 0.44 | 0.80 | 0.69 | 0.159 |
| D1 | 0.28 | 0.82 | 0.65 | 0.087 |
| D2 | 0.33 | 0.78 | 0.63 | 0.087 |

**Coverage vs reasoning on SYN:** in 22/23 positives, the original (pre-mutation) value is already inside A's 20k packet. Yet 6 of those 22 are detected in ≤1 of 3 runs. The misses on SYN are therefore verification failures (the model does not compare the move against the evidence it has), not retrieval failures.

## 2. valid46 pilot (run 1, diagnostic: contaminated by earlier design work)
| Arm | TP | FP | F1 | rcTP | DIFF | fixed/broke vs A |
|---|---|---|---|---|---|---|
| A | 13 | 2 | 0.684 | 8 | 5 | — |
| B | 11 | 4 | 0.579 | 9 | 2 | 3/7 |
| FULL | 10 | 3 | 0.556 | 9 | 1 | 4/8 |
| CTRL | 16 | 4 | 0.744 | 10 | 6 | 3/2 |
| C1 | 14 | 4 | 0.683 | 10 | 4 | 3/4 |
| C2 policy/evidence split | 10 | 8 | 0.488 | 6 | 4 | 4/13 (p=0.049, **worse**) |
| D1 | 13 | 2 | 0.684 | 10 | 3 | 1/1 |
| D2 | 13 | 2 | 0.684 | 10 | 3 | 1/1 |
| D3 (third packet) | 14 | 2 | 0.718 | 10 | 4 | 1/0 |

## 3. Why 20k beats 48k (`reports/diag_20k_48k.json`, frozen 3 runs, zero inference)
- **B does not lose A's evidence.** 20k units kept in the 48k packet: mean 0.995; exactly nested in 29/34 non-full rows. On ref15, B has complete reference sets 13/15 vs A 6/15.
- **B makes the model lenient.** ERROR on label-1 rows over 3 runs: 20k 43/69, 48k 26/69, FULL 27/69. On label-0: 10/69, 14/69, 8/69. Of the 7 rows A gets right and B gets wrong, 6 are positives where B says NO_ERROR. B's extra units (mean +37) almost never contain a newly required norm.
- The effect is consistent across repetitions, so it is not noise. It is **dilution/distraction**: more compliant-looking history and permissive policy text pulls the decision toward NO_ERROR. SYN-M1 confirms the sign (B 0.729 vs A 0.789, p=0.09 on rows). B is weaker there because SYN errors are local fabrications that the 20k packet already covers.

## 4. Multi-packet answers
- **2×20k vs 48k:** both ways of reading more evidence do worse than or equal to one 20k packet. C1 (2 independent 20k) 0.759 vs B 0.729 on SYN. Splitting the context avoids part of B's dilution but adds FPs (aggregation of two independent verdicts: FP 3.7 vs 2.0).
- **Policy/evidence split (C2) vs history split (C1/D):** C2 was clearly harmful on valid46 (F1 0.488, 13 broken, p=0.049). A policy-only inspector without the move's context over-flags obligations. C2 was dropped before SYN by the pre-registered rule.
- **Gap-directed 2nd pass (D2) vs fixed 2nd pass (D1):** no difference. They made identical decisions on valid46 and are within noise on SYN (0.757 vs 0.770). Both mainly re-ground A's verdict (fewer DIFFERENT reasons). Neither adds detections.
- **3rd packet (D3):** +1 TP on valid46 at ~+0.04 calls/row. It was not carried to SYN (the D-family slot went to D1/D2 by the rule). Not worth it given that D2 itself added nothing.
- **The matched-call control is the strongest multi-call arm.** CTRL (no new evidence, just a second sample of A plus the same aggregator) beats every multi-packet arm on both suites. Most of the multi-call "gain" is self-consistency, not new evidence.

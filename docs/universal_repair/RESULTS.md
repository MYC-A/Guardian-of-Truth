# RESULTS — universal repair, live Mistral `ministral-14b-2512` (final code = A2)

Source: `outputs/universal_repair/phase4/report.{json,md}` (validated records only; every arm, set and rep), stability
`phase4/stability.{json,md}`, miss funnel `phase3/funnel_<arm>_live.json`, cause judge `cause/` (see CAUSE_AND_GOLD_AUDIT.md).
Pre-amendment runs are kept: `runs_v50/` (before A1), `runs_a1/` + `phase4_a1/` (A1, before A2). V4r = stored V4 reproduced
exactly (parity 0 misses on all 8 stored set/reps; for valid46 r2–3 and the holdout V4r was run live with the same code).

## Detection, V4r → R_fix → R_comb (TP/FP/FN, F1)

| set#rep | V4r | R_fix (adoptable arm) | R_comb |
|---|---|---|---|
| valid46#1 | 15/3/8 .732 | 15/3/8 .732 | 15/3/8 .732 |
| valid46#2 | 17/3/6 .791 | 17/3/6 .791 | 18/3/5 .818 |
| valid46#3 | 12/2/11 .649 | 12/2/11 .649 | 12/2/11 .649 |
| LB1 | 22/3/6 .830 | 22/3/6 .830 | 23/3/5 .852 |
| LB2 | 20/2/3 .889 | **21/2/2 .913** (G3e) | 21/2/2 .913 |
| LB3#1 | 25/7/3 .833 | 25/7/3 .833 | 25/**8**/3 .820 |
| LB3#2 | 27/5/1 .900 | 27/5/1 .900 | 27/5/1 .900 |
| ext v2#1 | 36/1/16 .809 | 36/1/16 .809 | 35/1/17 .795 |
| ext v2#2 | 37/1/15 .822 | 37/1/15 .822 | 38/1/14 .835 |
| ext v2#3 | 38/1/14 .835 | 38/1/14 .835 | 38/1/14 .835 (+1/−1) |
| **holdout tau2h#1** | 27/4/14 .750 | 27/4/14 .750 | 27/4/14 .750 |
| **holdout tau2h#2** | 30/3/11 .811 | 30/3/11 .811 | 30/3/11 .811 |
| **holdout tau2h#3** | 28/2/13 .789 | 28/2/13 .789 | 28/2/13 .789 |
| pooled (13 set/reps) | 334/37/121 .809 | 335/37/120 .810 | 337/38/118 .812 |

ext strict-65: V4r .837/.851/.851, R_fix identical, R_comb .824/.864/.851. Ablations (8 dev set/reps, pooled): R_df 220/23/66 = V4,
R_pool 223/24/63 (+3 TP on ext/LB1, +1 FP lb3L_034), R_wit 217/22/69 (−1 FP lb2L_010, −3 label-TP on ext; see cause audit:
these were V4 accusations whose cause the sources contradict, e.g. ext_ret_019).
`*_mech` variants (accept an unrefuted full mechanical certificate) are identical to their arms on every live set/rep.

## Preserved findings (pre-registered)
| finding | V4r | R_fix | R_comb |
|---|---|---|---|
| H5e LB2 lb2L_037 | DF4 ✓ | DF4 ✓ | DF4 ✓ |
| CL3e LB3 lb3L_000 (r1, r2) | DF4 ✓ ✓ | DF4 ✓ ✓ | DF4 ✓ ✓ |
| BK3e LB3 lb3L_055 r2 Ems aggregation | Ems ✓ | Ems ✓ (after A2; A1 lost it to AT) | Ems ✓ |
| TL3e LB3 lb3L_003 r2 | DF4 ✓ | DF4 ✓ | DF4 ✓ |
| G3e LB2 lb2L_018 (known V4 regression) | ✗ | **Ems ✓** (MEMBER_OF orientation + closure) | Ems ✓ |

## Where misses are lost (P3 funnel, R_fix, 13 set/reps, 120 FN)
NO_TRIGGER 83 (base reviewer said OK and no focused checker fired), NO_CANDIDATE 27 (trigger fired, no admitted candidate),
VERIFIER_REFUTED 6, UNRESOLVED 4, NOT_EXECUTED 0. On tau2 (ext + holdout) all missed **semantic** errors (61) are NO_TRIGGER; the
NO_CANDIDATE misses are format-only gold causes (one-tool-call / message+call rules: 15). The repaired proof/evidence/verifier layers
can only act on the ~10 % of misses that reach them; the ceiling is upstream recall (reviewer + triggers). [v2 correction: not an oracle ceiling; see docs/universal_repair_v2/FUNNEL_V2.md]

## Cost
New detector calls 437 (2.01 M tokens) + judge calls 437 (377 judgements + 60 variance re-judgements, 1.82 M tokens); 0 transport failures. Budget cap 2500
(cumulative ledger `outputs/universal_repair/cache/mistral/attempts.jsonl`) never reached.

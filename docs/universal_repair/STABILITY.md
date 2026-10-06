# STABILITY — repeats, flips, paired differences (judge variance reported separately below)

Reps = Mistral attempts 0,1,2 (different sampling keys; the same rep index shares one sampled base reviewer across arms,
so arm differences inside one rep are paired). Source: `outputs/universal_repair/phase4/stability.{json,md}`.

## Detection range over reps
| set | arm | reps | TP | FP | FN | F1 | rows whose prediction flips between reps |
|---|---|---|---|---|---|---|---|
| ext_tau2 | R_comb | 3 | 35–38 | 1 | 14–17 | 0.795–0.835 | 13 |
| ext_tau2 | R_df | 3 | 36–38 | 1 | 14–16 | 0.809–0.835 | 13 |
| ext_tau2 | R_fix | 3 | 36–38 | 1 | 14–16 | 0.809–0.835 | 13 |
| ext_tau2 | R_pool | 3 | 36–39 | 1 | 13–16 | 0.809–0.848 | 11 |
| ext_tau2 | R_wit | 3 | 35–37 | 1 | 15–17 | 0.795–0.822 | 15 |
| ext_tau2 | V4r | 3 | 36–38 | 1 | 14–16 | 0.809–0.835 | 13 |
| hold_tau2h | R_comb | 3 | 27–30 | 2–4 | 11–14 | 0.75–0.811 | 13 |
| hold_tau2h | R_fix | 3 | 27–30 | 2–4 | 11–14 | 0.75–0.811 | 13 |
| hold_tau2h | V4r | 3 | 27–30 | 2–4 | 11–14 | 0.75–0.811 | 13 |
| lb3_long | R_comb | 2 | 25–27 | 5–8 | 1–3 | 0.82–0.9 | 5 |
| lb3_long | R_df | 2 | 25–27 | 5–7 | 1–3 | 0.833–0.9 | 6 |
| lb3_long | R_fix | 2 | 25–27 | 5–7 | 1–3 | 0.833–0.9 | 6 |
| lb3_long | R_pool | 2 | 25–27 | 5–8 | 1–3 | 0.82–0.9 | 5 |
| lb3_long | R_wit | 2 | 25–27 | 5–7 | 1–3 | 0.833–0.9 | 6 |
| lb3_long | V4r | 2 | 25–27 | 5–7 | 1–3 | 0.833–0.9 | 6 |
| valid46 | R_comb | 3 | 12–18 | 2–3 | 5–11 | 0.649–0.818 | 10 |
| valid46 | R_fix | 3 | 12–17 | 2–3 | 6–11 | 0.649–0.791 | 11 |
| valid46 | V4r | 3 | 12–17 | 2–3 | 6–11 | 0.649–0.791 | 11 |

LB1/LB2 have one stored rep only (no new LB reps were sampled to keep the lockboxes' frozen replies; their single-rep deltas are
therefore not a stability statement).

## Reading
* Rep-to-rep variance of the *same* arm dominates every arm effect: valid46 F1 0.649–0.791 for V4r (11 of 46 rows flip), holdout
  0.750–0.811 (13 of 51 flip), ext 0.809–0.835 (13 of 70 flip). The largest single-rep arm delta (R_comb valid46#2 +1 TP, ext ±1)
  is far inside this band.
* Paired rows that differ from V4r inside the same rep: **R_fix 1 of 13 set/reps** (LB2 G3e, +1 TP); R_comb 9 rows over 13
  set/reps (+6 TP, +1 FP, −2 TP). On the clean holdout both arms differ from V4r on **0** rows in all 3 reps.
* No arm changes the FP range on any set except R_comb/R_pool on LB3#1 (+1, lb3L_034).

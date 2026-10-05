# Verification v2 — final decision

**Default changes to profile `guard_adm2`** (= frozen A2 `guard` + admission v2). `ReviewConfig()` and the CLI default now
equal `guard_adm2`; `guard` stays available and byte-identical to integrated-v1 A2 (admission v1) for reproducibility.
Basis: pre-registered LB2 rule 1 passed (+2 TP, 0 FP, 0 lost), consistent with LB1-long (+7 TP/+1 FP),
LB1-short (+13/0) and the valid46 cache replay of 3 reps (+0/+2/+0 TP, 0 FP). Zero extra calls, same request bytes.

> **Amendment 3 audit (post-hoc, offline):** two of the rows below were partly artefacts of our own post-processing; see `AUDIT.md` for the corrected, narrower conclusions (verifier passes §6 after the generic quote fix; the counterfactual idea is untested on 3/4 residual misses because the needed variants were never generated).

**Not adopted (kept as research code, never default):**
| mechanism | status | evidence |
|---|---|---|
| C/D counterfactual probe (+ verifier) | not supported | LB1 frozen rule failed (D net not ≥2 above Bv); LB2 C′/D′ +0 vs A_adm2. Precise (0–1 false candidates) but adds almost no recall once admission is fixed. |
| B second skeptical review | not adopted | small recall gains bought with FPs (LB1-long +3 FP, LB2 +1 FP). |
| E checklist + CALCULATIONS table | not supported | LB2 E′ +1 cause-correct TP, +3 FP; Ev′ +0, +1 FP. |
| narrow verifier as filter (Bv/D/Ev/Av) | not useful | met the criterion on LB1 (9/11 kept, 2/3 rejected) but failed on LB2 (1/4 true kept); as an FP filter on A (Av) it loses TP on LB2 (−2) and valid46 (−4). |

**What remains open (the real bottleneck):** the evidence is present in the packets of the missed cases; failures are
semantic/computational — chronology of confirmations, prose arithmetic, non-ISO dates and business days, inactive
exceptions, later calls in a multi-call move. Next candidates: deterministic parsing of non-ISO dates/amounts in prose
into the CALCULATIONS table, a confirmation-chronology fact (what was confirmed vs executed), and a fresh, externally
authored lockbox with ≥3 repetitions and a second model family before any further claim.

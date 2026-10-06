# Guardian v6 — mechanical layers on top of R_fix

**Result.** v6 = R_fix + three code-checked layers. On the pre-registered fresh holdout2 (72 rows, task-disjoint, frozen
before any run) F1 goes .891/.915 → **.948/.948** (2 live reps), precision .93 → .94, specificity unchanged .875, and the
share of correct/grounded causes among detected errors goes 40% → **79%**. On dev (11 set-reps) F1 .810 → .860 with zero
new false positives. Self-review only (no independent reviewer available); gold of holdout2 built by the same author.

## Architecture
| layer | what it checks (code) | decides |
|---|---|---|
| F turn-shape | rules "≤ n tool calls per turn" / "no message together with a tool call", extracted from the policy by the model twice (must agree) with a verbatim quote checked by code; the move is counted by code | ERROR, cause = quoted rule + count |
| P provenance | identifier-like argument (digit/underscore token or self-declared placeholder) that appears in no user message, tool result, policy or declaration (declaration *examples* "such as …" and the agent's own text do not count); only on complete input | ERROR, cause = the invented value |
| S structural | identical repeat of a call whose result reported a failure; call of a tool the complete parsed catalog does not declare | ERROR |
| R_fix | unchanged v5 reviewer + components | otherwise |
Every accusation carries `certificate`: `MECHANICAL` (code-checked) or `MODEL` (reviewer hypothesis). CLI: `guardian-review --repair v6`.

## Results
Detection (TP/FP/FN/TN, F1, precision, specificity):

| data | R_fix | v6 |
|---|---|---|
| holdout2 rep1 | 41/3/7/21, F1 .891, P .932, Spec .875 | 46/3/2/21, **.948**, .939, .875 |
| holdout2 rep2 | 43/3/5/21, .915, .935, .875 | 46/3/2/21, **.948**, .939, .875 |
| holdout2 non-format rows (rep1) | 18/3/3/21 | 19/3/2/21 |
| dev pooled (11 set-reps) | 335/37/120/219, .810, .901, .855 | 371/37/84/219, **.860**, .909, .855 |
| dev tau2-family | F1 .805 | .868 |
| dev valid46 (human labels) | F1 .727 | .815 |
| dev lockboxes | F1 .868 | .868 (no layer fires; no rules of that kind) |

Cause quality of true positives (frozen judge v2):

| | R_fix correct core | R_fix grounded (correct+alternative) | v6 correct core | v6 grounded |
|---|---|---|---|---|
| dev | 163/335 (49%) | 168 (50%) | 262/371 (71%) | 305 (82%) |
| holdout2 | 28/84 (33%) | 34 (40%) | 65/92 (71%) | 73 (79%) |
MECHANICAL causes: 186/207 grounded on dev, 64/70 on holdout2 (6 judge-inconsistent, 0 unsupported). MODEL causes stay weak (holdout2 9/22).

## Measured and rejected (negative results, kept as evidence)
- **G1, verifying the reviewer's accusation** (318 accusations): verifier SUPPORTED 75% of correct, 67% of ungrounded and 60% of FP accusations — not a grounding filter.
- **H, per-action rule checklist + verifier** (36 rows): SUPPORTED claims on 4/14 negatives, incl. self-contradictory ones; stopped.
- **C2, confirmation re-check** (code-checked "user said yes to the confirmation request" → re-review): dev specificity .855 → .891 (lockboxes .844 → .917) but F1 .860 → .854; on holdout2 it only lost 1 TP per rep. Kept as code, **not** in the default, per the pre-registration.
- Majority vote over 3 reps: no gain over a single rep.

## Limitations / remaining gaps
- Layer F and the tau2-family format gold express the same policy rule (partly circular there); valid46 (human labels, 8/8) and the non-format subset are the independent evidence. The gain is concentrated in policies that state turn-shape rules.
- P/S fire rarely (dev 5+9 rows, all positive; holdout2 0) — small evidence of precision.
- Remaining FN: eligibility/entity errors (wrong line, cancellation conditions, item variants) that the 14B model misses; remaining FP: "no confirmation" boilerplate on lockboxes (C2 fixes it there but costs recall on tau2). Model-only layers did not help with ministral-14b; a stronger model is the lever for these.
- Holdout2 is small (72 rows, 24 negatives) and annotated by the same author (DROP-only review, 7 drops, listed in MANIFEST).

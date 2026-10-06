# Pre-registration: frozen120 (written and committed BEFORE any Guardian run on these rows)

## Set
- `outputs/guardian_v6_fix/frozen120/` — 40 hand-written templates × 3 domain skins (telecom, retail, banking) = 120 rows,
  generator `experiments/guardian_v6_fix/build_frozen.py`. SHA-256: inputs `845eec41…7ba72`, gold `1592c074…62`,
  generator `291e30c5…eebced`; per-row hashes in `MANIFEST.json`.
- Gold: label 0/1/UNKNOWN + kind + reason per template, written by the author from the template construction (what the
  agent does vs the policy/tools), not from Guardian code. **No independent annotator** was available; gold is
  self-annotated and self-reviewed only. UNKNOWN (S07: identical repeat after a permanent error with no retry rule, 3 rows)
  is excluded from metrics.
- Splits by template family (no template in two splits): regression 13 templates (39 rows: mirrors the contrast/external
  tests the fix was designed on — NOT evidence of generalisation), dev 13 (39), holdout 14 (42, 3 UNKNOWN). Holdout
  templates use mechanisms not present in the unit tests (typo tool, false success claim, wrong amount, other entity,
  other-key id, long history, digits in email, user-subject rule, no rule, confirmation, scoped rule).
- Before freezing only parse sanity was checked (every row builds a packet; 3 rows — P14 — are incomplete at 20k by design).
- Categories (from gold kind): format_only = F1/F2 (turn shape); semantic_only = every other label-1 kind; correct = 0.
  No row mixes both.

## Systems (all mistral `ministral-14b-2512`, temperature as in the repo transport)
1. **R_fix** — `run_v5` arm R_fix, packet budget 20k, reps 1 and 2 (`attempt` 0/1).
2. **original v6** — R_fix record of the same rep + `guardian_truth.v6` layers (400k, its own F extraction;
   cache copied to `outputs/guardian_v6_fix/cache/v6frules`, the original cache is not touched).
3. **v6fix** — R_fix record + `guardian_truth.v6fix` layers F,S,P; layer budget 20k (primary: same context as R_fix)
   and 400k (secondary); F extraction replicates A (attempts 0/1) and B (2/3).
4. **v6fix F-only** — same, only layer F.
Decision of a layer system: ERROR if any MECHANICAL finding (v6fix) / any finding (original v6), else R_fix decision.

## Metrics
TP/FP/FN/TN, precision, recall, specificity, F1 per split and per category (format_only / semantic_only / correct),
per rep and pooled; per-layer decisive findings on label-0 rows (= false mechanical accusations) and label-1 rows;
rows whose decision differs from R_fix; model calls (transport counts).

## Selection / success criteria (fixed now)
- C1 (primary safety): v6fix (20k, replicate A) has **0 MECHANICAL findings on label-0 rows** in every split.
- C2 (primary benefit, holdout only): v6fix F1 ≥ R_fix F1 in both reps, with FP(v6fix) ≤ FP(R_fix).
- C3 (where): the benefit is reported separately for format_only and semantic_only; if TP gains are only in
  format_only, the report says the advantage is format-only.
- C4: original v6 vs v6fix: count of label-0 rows that original v6 accuses and v6fix does not, and vice versa.
- Any change to code/gold after the first evaluation is logged as post-hoc in the report and evaluated separately.

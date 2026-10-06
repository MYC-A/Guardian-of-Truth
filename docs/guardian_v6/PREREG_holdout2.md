# Pre-registration: v6 evaluation on holdout2 (written before any v6/R_fix score on holdout2 was looked at)

- Data: `outputs/guardian_v6/holdout2` (72 rows, 48/24, frozen in commit d14d1fd6 before any run; gold = Amendment-2 method
  of tau2h: F1/F2 format regex + tau2 oracle writes, manual review DROP-only, 7 drops listed in MANIFEST).
- Systems (all frozen at this commit):
  - `R_fix` (baseline, v2 code), 2 live reps.
  - `v6` = R_fix + mechanical layers F (turn-shape rules), P (argument provenance), S (failed-call repeat / undeclared tool). **Primary.**
  - `v6+C2` = v6 + confirmation re-check of A-owned "missing confirmation" accusations (precision mode). Secondary.
- Selection rule fixed on dev (11 set-reps, 711 row-decisions): primary = v6 (dev F1 .860 vs .854 for v6+C2, .810 R_fix).
- Metrics: TP/FP/FN/TN, F1, precision, recall, specificity per rep and pooled; plus the non-format subset (rows whose gold
  is not format-only) because F1/F2 gold and layer F express the same policy rule (partly circular on tau2-family data).
- Cause quality: judge v2 (frozen prompt) on v6 positives; certificate share (MECHANICAL vs MODEL).
- No change of code, thresholds or lexicons after this file; any later change is reported as post-hoc.

# Frozen-generation note admission ablation

Research only; production admission and defaults unchanged. Candidate motivated
by dev520 structural failures, so dev is exploratory, not an untouched holdout.
No threshold/weight tuning, no additional generation or new weights.

One vLLM load, same A6000 configuration/tokenizer/exact YES-NO contract and original
final source/checklist. Three fresh-scored arms on all520 dev rows:

- no_notes: checklist final without generated notes;
- strict: current whole-document admission, byte/token-identical to saved final;
- partial: same generated JSON; admit each valid check independently, explicitly
  mark partial admission and incomplete coverage. Each retained check passes the
  unchanged strict validator with the exact citable source IDs. No invented IDs,
  rewritten assessments, clipping strings or recovery of truncated JSON.

Whole JSON envelope keys/types/list-count limits remain mandatory. Partial notes
must retain at least one valid check. VALID strict documents remain identical.
Same input budgets; oversized notes are still dropped and reported. Schema-valid
citations never establish semantic truth. Partial module is not wired into runtime.

Primary comparison: partial vs strict at quota .40. Predeclared diagnostics .30,
strict vs no_notes, AUC/AP, per-domain results (airlines+healthcare primary external
slice, insurance separately), delivery and source/coverage identity. Paired grouped
bootstrap2000/seed20261018 uses all groups, including TN-only groups. Old bootstrap
omitted zero-count TN-only groups; reanalysis changes only uncertainty estimates,
not scores, predictions or F1. A regression test covers this correction.

Reuse saved generation, but rescore all3 arms, including unchanged strict baseline;
never substitute saved final scores for fresh ones. This is a counterfactual final
ablation, not an independent full repeat, nor evidence of competition timing.
Verify source file/row/hash/tokenizer/prepass hashes and reproduce every strict
final input/delivery before any GPU scoring. Save all prompts and exact receipts.
No labels are read by the model runner; gold-side analysis is a separate process.

Same16 rows per batch per arm; rotate arm execution order across batches, APC on.
Report numerical score differences on identical strict/partial prompts and between
fresh strict and original final; exactness is not bitwise repeatability. Report
role wall/tokens/cache, not an unbiased throughput competition between arms.

First dev520 replay only. Guardian regression/valid46 follow if informative; no
automatic full eval1893 or three repetitions. If partial adds only delivery without
quality benefit, do not promote it. A useful dev effect requires further independent
evaluation. B/no_notes helps separate checklist from notes; this is not a blind
ablation or full A/B/C/D, and it does not isolate benefit of generation itself.

# V12: frozen transfer check, 20 October 2026

Freeze before new inference. This is EXPLORATORY: compli_eval (1893 rows) has
already evaluated older 4B adapters. It is neither untouched nor private data.
No row, label, derivative, error explanation or selected example from this set
may enter training. No tuning or choosing a new threshold from these results.

Compare the complete current 35B overall/open-review/MAX control at quota .40,
then the same candidate-only source-supported verifier with (a) no adapter and
(b) the frozen V7 layers16 adapter. Review limit 192, temperature 0, seed 0,
chunk 64; exact YES-minus-NO log odds, veto at score <=0. Invalid, UNKNOWN,
truncated, oversized or absent review preserves the accusation. Hard positives
are protected. No quota refill. Reuse actual saved primary input, without
rebuilding or substituting context. No prediction cache, no quality retries.

Research runtime: eager synchronous LoRA-capable engine, chunk 64; extended
research deadline to finish the larger cohort. This is NOT a competition-time
or packaged cold-start measurement. Compiler cache reuse is allowed and named.
Outer allocation is finite, 7200 seconds; stop/export failures and partial runs.

Before labels: freeze complete baseline scores/predictions and BOTH verifier
outputs, record hashes, prove full exact control coverage, token round trips,
source quote admission and adapter GPU weight coverage. Only then join labels
by exact ID. Publish all arms, TP/FP/FN/TN, admission and domain breakdowns.
Do not select the best of repeated seeds. Do not present repeated generations
or turns from the same conversation as independent tasks.

The transfer hypothesis is lower FP with <=2% loss of baseline TP. A useful
LoRA-specific result must also beat the base verifier, rather than merely the
unfiltered control. Report failures and domain regressions. This check alone
does not satisfy the original human-reviewed holdout, independence or ZIP gates.
Production defaults, submitted archives and competition attempts stay unchanged.

New training data work proceeds separately: unused source components only,
pinned licenses/revisions, current-turn policy/state predicates, complete paired
correct/incorrect twins, no reward-only labels, no synthetic padding, no evaluation
seeds. Split source components before mining. Model failure mining is TRAIN-only.

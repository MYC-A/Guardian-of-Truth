# Guardian 6q submission — 18.10.2026

Run from the extracted archive root:

```bash
python scripts/predict.py --input INPUT.parquet --output OUTPUT.parquet
```

The selected profile is `judge-6q-mean-z-20261018`, legacy context, hints on,
review off. One Qwen3.6 AWQ instance scores six separate unchanged questions:
overall, values, actions, tool_use, policy, refusal. Each call uses one output
token and the exact YES/NO log-odds scoring contract at temperature 1.0.
There is no blind prepass and no generation of a review note.

Unlike the collection-only JUDGE_AB_QUESTIONS profile, this archive selects
`aggregate=mean_z` with ALL six keys. Each question's scores are standardized
across the scored input rows (population standard deviation; zero variance
uses 1). The six standardized scores receive equal weight. This is an
untrained, experimental aggregation rule, not a calibrated probability.
The same .30 ranking rule and final mechanical hard override remain in force.

Within a chunk of 16 rows, primary is durably written before five extra
questions. Every variant uses the same built context, response and cap;
only the final question changes. Extra input hashes/statuses are retained.
The global `primary(aggregate_incomplete)` fallback remains: missing exact
extra scores for any primary-scored row revert the entire ranking to overall.
Unscored rows retain the existing technical fallback, never a fabricated
model NO. Partial rankings are not mixed. A technical fallback or an unchanged
top-.30 set can still produce the same submission score as the baseline.

Stop new work at 1380 seconds, kill stage at 1530, watchdog at 1680 from predict;
the external 1800-second budget also includes startup/installation. Extra work
is deadline-aware and may not finish. Prefix caching is enabled, but actual
cache counters and target-GPU speed have not been measured for this profile.

GPU_UNTESTED: no quality gain, exact coverage, or contest runtime guarantee.
CPU/fake-vLLM tests verify routing and failure handling only. The implementation
must pass a fixture where mean_z changes the exported labels relative to overall,
plus incomplete/inexact extras tests that explicitly exercise the global fallback.
No label/explanation is passed to inference. Repository production defaults and
the existing blind archive remain unchanged.

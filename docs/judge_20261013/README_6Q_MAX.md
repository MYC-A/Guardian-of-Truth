# Guardian 6q max_logit — 18.10.2026

```bash
python scripts/predict.py --input INPUT.parquet --output OUTPUT.parquet
```

Selected profile: JUDGE_6Q_MAX.json, legacy, hints on, review off, chunk 16,
per_chunk schedule. Six unchanged questions, one Qwen3.6 AWQ instance, one
scoring token per question, T=1.0, exact finite YES/NO log-odds only.

For EACH row: max_logit = max of all available exact scores among overall,
values, actions, tool_use, policy, refusal. Missing/error/bounded/inexact
scores are absent, never zero or NO. There is NO complete-row/complete-question
gate and NO global fallback to overall. A completed extra score is used even
if the same question is unavailable for other rows, or every other extra fails.
With only overall available the same function naturally returns overall.
With no finite exact score the existing technical/mechanical output remains.
More negative scores cannot cancel a higher error score. .30 quota and final
hard override remain unchanged: one model YES does not automatically force label 1.

This is a fixed, untrained aggregation heuristic. Different questions have
different unmeasured calibration; max does not make their scores calibrated
probabilities. More available questions create more chances for a false positive.
Partial coverage may depend on row length/deadlines. All these quality risks
remain unmeasured; a model's high YES score is not verified proof of a violation.

Primary results are durable before extras; extras preserve exact/inexact/missing/
error status and actual prompt SHA256. Same row context/cap/response for every
variant; only the final question changes. Failed later work never discards
already saved exact scores. ranked_rows/coverage and per-question coverage are
logged independently of primary coverage. Literal/duplicate ids are preserved.

No blind, shuffle, trained normalizer or result cache. GPU_UNTESTED: quality,
coverage, real cache counters/VRAM and whole-script runtime are not measured.
Stop new work 1380, kill stage 1530, watchdog 1680 from predict remain unchanged;
external 1800 seconds includes startup. If extras never start, or the top-.30
set does not change, the platform score may still equal the baseline.
The old strict mean_z and single-pass production profiles remain unchanged.

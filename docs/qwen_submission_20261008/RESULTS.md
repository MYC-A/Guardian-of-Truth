# Offline Qwen package: measured results, 2026-10-08

This is a packaging and serving comparison of the existing B2 method. No new
quality improvement is claimed from a different fresh model output.

## Complete 8-slot control

All46 original valid rows were processed on one A10080GB with Qwen Q8_0,
32768 context tokens/slot and unchanged B2 prompts/budgets. The previous thinking
experiment and idle serving instance were stopped before this control.

|Metric|Result|
|---|---:|
|TP / FP / FN / TN|14 / 0 / 9 / 23|
|Binary F1|0.7567567568|
|Recorded CLI elapsed|1615.49s (26min55s)|
|Actual completion receipts|179|
|Input / output tokens|687746 / 111936|

Time includes input loading, owned model initialization, processing and shutdown.
It excludes launcher startup and writing a successful final prediction file:
the frozen wrapper exited1 because of its optional-prepass failure bug. Ten rows
had valid admitted NO_ERROR reviews but were mislabeled as primary failures.
The separate corrected offline projection yields46/46 predictions and the score
above, with zero new model calls. A short CPU ZIP smoke overlapped this control;
it was not a bare-engine benchmark. Model initialization was process-cold, not a
controlled cold OS page-cache measurement.

The original raw records, nonzero exit receipt and run summary are retained:
`outputs/qwen_submission_20261008/bench-baseline-20261008/`.
The amended result is a distinct phase:
`outputs/qwen_submission_20261008/bench-baseline-projection-v2-20261008/`.

Reference input SHA256:
`8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`.
This equals the original Git blob contents at403d811e:valid.parquet. Legacy
traces lack individual row hashes; the report explicitly records phase-level
binding only. Future CLI traces include per-row prompt/response hashes.

## Performance arm still running

The queued whole-valid46 run started after the control terminated: workers16,
FlashAttention on, batch8192, microbatch512; same weights/context/prompts/budgets.
Its terminal external timing and corrected full-input score are pending. No
default profile is changed on partial progress.

548 is a participant-reported evaluated cohort, not a confirmed complete input
size. Different lengths and triggered checks can change total cost substantially.
The valid46 time alone proves neither that the hidden input fits30min nor that
it cannot fit. Use the measured comparison and an actual platform run to resolve
that uncertainty; do not present linear extrapolation as a platform result.

## Native runtime / archive checks

- Local targeted suite:25 passed,2 POSIX skips on Windows.
- Actual Linux signal ownership test:2 passed; harmless subprocess lifecycle,
  not a blocked GPU HTTP-worker stress test.
- Runtime-only ZIP roundtrip:1,851,469,211 bytes; unzip, offline `pip install`,
  empty CLI Parquet output and bundled native imports succeeded as user nobody.
  CPU smoke elapsed23.07s. The test used a declared tiny weight fixture;
  actual28.6GB model roundtrip is not implied.
- The first CPU-smoke attempt used the build venv, which has no pip. The second
  explicitly used the platform `/usr/bin/python3` for install/dispatch and passed.
- Actual full model executed in the live46 control. Complete ZIP transfer and
  local per-file manifest/CRC validation are underway.
- Full Windows raw replay rebuilt179 exact request/attempt identities across
  all46 rows, consumed all179 frozen receipts and reproduced every binary
  decision, winning owner and accusation text/target, with zero network calls
  and zero mismatches against the amended projection. This is processing
  reproducibility, not a new inference repetition.
- Dockerfile is provided. Docker build/run is NOT_EXECUTED: no Docker/Podman or
  daemon socket is available, and namespace creation is denied. The native
  runtime checks are not represented as an actual Docker-engine test.

Receipts: `docs/qwen_submission_20261008/receipts/`. No API/private credentials,
model weights, historic predictions or gold are included in the submission ZIP.

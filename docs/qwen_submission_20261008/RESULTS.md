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

## Completed performance comparison

The queued whole-valid46 run started after the control terminated: workers16,
FlashAttention on, batch8192, microbatch512; same weights/context/prompts/budgets.
It processed all46 rows. External launcher timing was1641.955s (27min22s),
exit1 due to the same frozen wrapper bug. The separate amended projection has
46/46 valid predictions:14TP/1FP/9FN/22TN, F1 .7368421053. Nine optional fallback
markers were incorrectly counted as failures in its frozen CLI report.

|Profile|TP|FP|FN|F1|Recorded elapsed|
|---|---:|---:|---:|---:|---:|
|8 slots, baseline|14|0|9|.7568|1615.49s, internal CLI clock|
|16 slots, FA on, batch8192|14|1|9|.7368|1641.96s, external launcher clock|

Clock scopes differ slightly, so the27-second difference is not a precise speed
regression estimate. This single comparison does not demonstrate an acceleration
or improved quality. Keep the8-slot default. It does not establish repeatability
of either fresh model output. Background archive construction/transfer also ran
during part of the16-slot arm; this is an application-level comparison, not an
isolated kernel benchmark.

Five binary decisions differ: two baseline true positives are lost, two other
true positives are gained, and one false positive is added. The16-slot arm made
180 calls,708390 input and122727 output tokens, versus179/687746/111936 in the
control. Generated output is9.64% larger, so elapsed time alone does not isolate
engine speed from changed model output length. The per-row changes are recorded
in `receipts/paired_binary_changes.json`; IDs are diagnostic only.

The original and amended16-slot phases are retained under
`outputs/qwen_submission_20261008/bench-speed16-20261008/` and
`bench-speed16-projection-v2-20261008/`. No old output is overwritten.

548 is a participant-reported evaluated cohort, not a confirmed complete input
size. Different lengths and triggered checks can change total cost substantially.
The valid46 time alone proves neither that the hidden input fits30min nor that
it cannot fit. Use the measured comparison and an actual platform run to resolve
that uncertainty; do not present linear extrapolation as a platform result.

## Native runtime / archive checks

- Local targeted suite:27 passed,2 POSIX skips on Windows, including authenticated
  range transfer and refusal to publish a tampered archive.
- Actual Linux signal ownership test:2 passed; harmless subprocess lifecycle,
  not a blocked GPU HTTP-worker stress test.
- Runtime-only ZIP roundtrip:1,851,469,211 bytes; unzip, offline `pip install`,
  empty CLI Parquet output and bundled native imports succeeded as user nobody.
  CPU smoke elapsed23.07s. The test used a declared tiny weight fixture;
  actual28.6GB model roundtrip is not implied.
- The first CPU-smoke attempt used the build venv, which has no pip. The second
  explicitly used the platform `/usr/bin/python3` for install/dispatch and passed.
- Actual full model executed in both live46 arms. Historical full ZIP was built on the server:
  30,447,402,247 bytes, SHA256
  `46317b9570c76833771f14468e045e642f9802c7b516fba8234fefa23a493835`.
  The server is now stopped. This ZIP lived in volatile `/dev/shm`, so it is not
  considered available after Stop. Local partial files are not READY. A separate
  CPU CI rebuild and the exact public weight download replace this transfer;
  see RUNTIME_REBUILD.md. New-runtime GPU inference remains NOT_EXECUTED.
- Full Windows raw replay rebuilt179 exact request/attempt identities across
  all46 rows, consumed all179 frozen receipts and reproduced every binary
  decision, winning owner and accusation text/target, with zero network calls
  and zero mismatches against the amended projection. This is processing
  reproducibility, not a new inference repetition.
- The16-slot raw replay also rebuilt180/180 exact request/attempt identities
  over all46 rows, consumed all180 frozen receipts and had zero final
  binary/owner/accusation mismatches. The same projection is used in both arms.
- Historical Docker build/run was NOT_EXECUTED: no Docker/Podman or daemon socket
  was available and namespace creation was denied. New CPU CI explicitly runs a
  real Docker image and both full raw replay phases. Its results are a separate
  phase and must be recorded after completion, rather than inferred from YAML.

Receipts: `docs/qwen_submission_20261008/receipts/`. No API/private credentials,
model weights, historic predictions or gold are included in the submission ZIP.

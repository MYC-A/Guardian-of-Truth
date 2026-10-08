# Measured workload and speed: initial evidence, 2026-10-08

18.3 rows/min equals548/30: a required rate for a hypothetical548-row input and
30-minute budget. It is not an observed GPU generation speed. The548-row count
comes from a participant's confusion matrix, not a confirmed whole-input size.

Read-only inspection on the A10080GB PCIe server:

```
/workspace/guardian/repos/Guardian-of-Truth/outputs/guardian_local_a100/llamacpp/
qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/valid46/B2_rep1.jsonl
```

All46 unique records were inspected. Per stage (means across46 cached usage
receipts, not fresh measurements):

|Stage|Input tokens|Output tokens|
|---|---:|---:|
|Prompt-only blind pre-analysis|3884.89|1443.50|
|Main reviewer|6942.11|607.46|
|Combined primary stages|10827.00|2050.96|

The final label has one digit; the model generates supporting JSON analyses.
Additional DF/Ems/all-target/verifier and policy-extraction requests can follow.
At18.3 rows/min this workload alone requires~626 generated tokens/s aggregate,
plus~3302 input tokens/s, before additional requests and initialization. This
calculation is not a prediction of achievable throughput.

Different earlier diagnostic phase (DO NOT call this a B2 timing benchmark):
phase2_compact has172 row-arm records,184 actual HTTP calls,1238524 input and
32011 output tokens. The span between completed HTTP timestamps is1431.12s;
the whole phase duration previously recorded is1489.87s. Thus aggregate output
is~21.5 tokens/s over whole phase, despite~6.9 row-arm records/min. Two arms
cover86 distinct inputs. This includes queue/prefill, not pure decode throughput.

At the initial inspection two Qwen instances occupied79071/81920MiB, GPU utilization100%.
One is the nonthinking baseline, the other an active thinking experiment.
Two resident models do not prove simultaneous competing inference; do not infer
CPU offload from process RSS or total VRAM alone. Baseline starts with -ngl999;
the current log does not expose exact offload layer counts. No claim that full
GPU offload has been independently proved is made yet.

Optimization checks to perform on identical full inputs: one model process;
workers/slots4 vs8; FlashAttention; batch/prefill settings; warm prefix caching;
stage-specific time/token/queue metrics. Smaller pre-analysis schemas or removal
of a stage are separate quality arms. No silent output cap reduction, thinking
switch or CPU fallback is part of the measured baseline.

## Live comparison in progress (not completed results)

After the user stopped the thinking experiment, the old idle baseline instance
was stopped as well. The packaging control now owns a single model process.
Full valid46 control: workers8,32768 tokens/slot, Q8 weights and unchanged B2 wire.
Queued candidate: workers16, same context/weights/prompts, FlashAttention on,
batch8192, microbatch512. Each phase writes to a fresh directory under
`/workspace/guardian/submission/bench-{baseline,speed16}-20261008/`.

A partial control trace exposed a packaging classification bug: a skipped blind
analysis injection had an explicit fallback to the unchanged reviewer. The
reviewer returned a valid admitted NO_ERROR, but the wrapper classified the
optional pre-injection budget marker as a primary failure. The fix checks the
terminal primary receipt separately; the auxiliary gap remains visible. A failed
actual reviewer still cannot produce a negative prediction. This changes no
model request. Running stages remain unchanged; corrected projection of their
raw traces must be reported separately rather than editing historical outputs.

Partial progress does not establish a complete quality score or compliance with
the30-minute whole-input limit. Final receipts and paired results are pending.

See EXVRAM_RELEVANCE.md for the low-bit article and the limits of that comparison.

# Small platform environment probe — 2026-10-11

Archive: `A:/Guardian-submissions/guardian-platform-env-probe-20261011.zip`.
Size: **5752 bytes**. SHA256:
`ab6e6b7a8937d77fd64ba9ded7f0649eec59e05a7882f8b40d49458194a4d785`.

The original Cloud job exposes no further inner logs. This separate tiny ZIP
collects the host environment without retransferring 36GB of model/runtime.
It does not replace or modify the old competition ZIP.

## Operator use

1. Upload this tiny ZIP as a separate diagnostic run in the same platform.
2. Run it once. The log contains `GUARDIAN_ENV_PROBE` JSON lines.
3. Save/share the full resulting platform log.

**Expected behavior: exit code2 and a failed pipeline after the diagnostic
report. No predictions file is created. Never submit this diagnostic archive
for competition scoring.** No input file or gold is read and no model is loaded.
It may consume one platform run attempt; it is not a quality experiment.

## Evidence collected and scope

- Host Python and installed vLLM/Torch/Transformers/Triton/FlashInfer versions.
- Selected CUDA/driver paths, tool locations and cgroup memory limits/events.
- Driver-library visibility; Torch CUDA visibility, GPU capability and total/free
  memory; a tiny16x16 FP16 matmul; vLLM import/platform detection.
- Bounded stdout/stderr, secret-value redaction and individually bounded child
  phases. Linux descendants are signalled through owner/session-verified pidfds;
  no unrelated worker/experiment is terminated.

This tests the **host environment**, not the private bundled loader, Qwen
weight loading, FP8/Marlin kernels, CUDA graphs, B2 inference or its F1/time.
It can narrow the original startup failure but is not its inner traceback.

131 tests passed,2 real Linux descendant tests skipped on Windows. Actual
offline `pip wheel --no-index --no-deps --no-build-isolation` passed after
extracting this ZIP. Archive entries/CRC/manifests and no-overwrite were checked.
No live platform/GPU probe has been performed by this agent.

## Other participant's FP8 report

The pasted report concerns FP8 MoE plus runtime LoRA. Our packed config is
`Qwen3_5ForConditionalGeneration`/`qwen3_5_text`, without expert configuration;
the adapter has no LoRA runtime flags. The successful graph16 server log says
`Selected MarlinFP8ScaledMMLinearKernel for Fp8LinearMethod` and explicitly
describes weight-only FP8 on its A100. The foreign fp8e4nv traceback is therefore
not an established explanation for our generic `VLLM_START_FAILED`.
No vLLM0.30 upgrade is applied without evidence or a measured new profile.

# Checked runtime-only startup probe — 2026-10-11

This is a diagnostic archive, **not a competition submission**. Upload it as a
separate run, then send the common platform log. Exit2 after the final diagnostic
line and no predictions file are intentional. No input/gold is read.

The final archive path, byte size, SHA256, build/test receipts and published SHA
are recorded in CHECKED_STARTUP_PROBE_FINAL.md after successful assembly.

## What changed from the proposed7361d0d3 probe

- Weight exclusion applies only to model files. Runtime .pth hooks/native .bin
  files are retained. The old global suffix assertion rejected guardian-vendor.pth
  and prevented a real runtime build; this was reproduced offline.
- Runtime and model metadata are copied with their original compressed ZIP
  records and Unix modes. Normal/ZIP64 records with streaming data descriptors
  are supported. No second compression of all11GB vendor libraries is needed.
- Every copied member is checked by CRC/SHA256 against the source manifest;
  generated code, final inventory and output archive SHA are verified separately.
  Missing weight files are deliberate. The omitted30.9GB checkpoint data is not
  rehashed or certified by this diagnostic build.
- The ineffective driver-bridge arm is removed: its LD_LIBRARY_PATH was erased
  by the unchanged launcher. The compact actual platform probe already proved
  cuInit0, CUDA/NVML access and device enumeration under the original launcher.
- Runtime supervision, bounded logs, phase budgets and termination cleanup are
  repaired. Each variant gets fresh caches. No repeated HTTP model retries.

## What will run

Platform facts, bounded bundled-library/Torch/Triton checks, then the private
vLLM command with the existing graphs16/context32768/seq16/FP8 profile and
**--load-format dummy**. A separate host-vLLM startup is diagnostic, not a silent
replacement of the submission runtime. The primary original settings are kept.

Host Transformers4.57.1 fails AutoConfig.for_model(qwen3_5) in isolation, but
vendored vLLM0.19.1 transformers_utils/config.py registers its own Qwen3_5Config.
Therefore the earlier isolated AutoConfig failure is insufficient to declare
host vLLM unsupported. Its real startup is measured instead.

The supervisor limits execution to an absolute1500-second diagnostic budget,
with bounded phases and teardown. Do not treat this as a measured GPU runtime
or a guarantee against an externally killed container/uninterruptible kernel.
Budget-exhausted stages are explicitly skipped. Startup/import errors appear
in the common log, with bounded traceback/head/tail excerpts and redaction.

## Dummy weights: useful boundary test, not equivalence

The actual vLLM DummyModelLoader skips checkpoint downloading/loading, constructs
the configured architecture and initializes parameters randomly. BaseModelLoader
then invokes real weight postprocessing. This can exercise FP8/Marlin startup,
profiling, CUDA graphs and KV allocation **if earlier stages succeed**.

It does not establish that all those stages succeed. Random weights/scales and
temporary FP16 initialization allocations differ from checkpoint loading; peak
memory and results can differ. A dummy-specific failure may not reproduce the
original failure. A successful dummy startup does not validate real checkpoint
bytes, safetensors loading, B2 predictions, quality or the full/private runtime.
The tiny completion exercises the running backend only; its text has no quality
meaning. No scores are produced.

## Read the next log

- A bundled import/driver/JIT failure gives a concrete trace to repair.
- Dummy engine failure must be checked against the original path and whether
  random initialization contributed before assigning the original cause.
- Bundled dummy success narrows the remaining gap to real checkpoint loading
  or differences of the real entrypoint/environment. It is not full validation.
- Host startup success offers an alternative runtime candidate; it still needs
  actual weights and compatibility checks before replacing the measured bundle.

The original36.58GB contest ZIP, Q8 backup, actual model downloads and previous
phase artifacts are preserved. This probe includes all original runtime wheels,
licenses, config and tokenizer metadata, but none of the model weight shards.

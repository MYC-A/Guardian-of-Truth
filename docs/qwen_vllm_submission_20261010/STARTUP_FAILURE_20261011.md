# Cloud.ru startup failure — 2026-10-11

Job `lm-mpi-job-88aac27d-e4b2-403c-810c-fdfcf81faa6a` reached the public
entrypoint and spawned the vLLM API process. `process.poll() != None` then
raised `VLLM_START_FAILED`. This is an early process exit, not the separate
`VLLM_STARTUP_DEADLINE` branch. No B2 completion or prediction happened.
The earlier platform SSH public-key warning did not prevent worker startup.

## Confirmed diagnostic defect

The original adapter saved the subprocess stdout/stderr only in
`/tmp/guardian-vllm-submission-f470i3m3/run/vllm-server.log`. Public stderr
contained a generic exception and only the receipts directory. The supplied
full 2,756-byte platform log contains no inner vLLM traceback or returncode.
That log is insufficient to establish the underlying failure.

## Isolated diagnostic repair

Branch `fix/qwen-vllm-startup-diagnostics-20261011` adds:

- Before switching to bundled Python, a bounded host metadata record:
  Python/package versions, selected CUDA/driver paths, nvcc location and
  libcuda load visibility. It neither imports Torch nor initializes CUDA;
  unrelated environment variables and credentials are not dumped.
- On startup failure: returncode before cleanup, time since Popen, up to64KiB
  of post-cleanup server log, structured `startup_failure.json` and marked
  stderr output. Local API key and ownership token are redacted.
- The original startup exception survives diagnostic/cleanup failures.

112 adapter/public-entrypoint/B2 tests passed. Independent reviewer implemented
and checked failure diagnostics; root reviewed the diff and checked public
host telemetry. No model, prompts, inference parameters, new retries, output
fallback or successful-run request sequence were changed. The old ZIP is
preserved. This code repair is not yet a new assembled/uploaded archive.

## Hypotheses, not assigned causes

Actual launcher removes LD_LIBRARY_PATH and uses archive directories in its
private loader path. A host driver exposed only through a custom path could
be hidden. The packaged Triton driver can also use TRITON_LIBCUDA_PATH,
ldconfig and LD_LIBRARY_PATH. This risk is real but needs the inner error.

The archive contains Triton ptxas and GNU tools, not nvcc/nvlink. FlashInfer
may need CUDA JIT tools or a prebuilt JIT cache; its default cache may be
HOME/.cache/flashinfer, outside the explicitly configured caches. Their use
in this failed startup is not yet established. MPI inheritance alone does
not establish MPI as the cause. Returncode -9 alone would not prove OOM.

## Platform-installed vLLM

The user supplied a September11 organizer comment reporting vLLM0.19.1.
This makes the platform environment a candidate alternative, not a verified
dependency match. Actual Python/PyTorch/Transformers/CUDA and driver visibility
must be observed before replacing bundled runtime or changing libraries.
Official vLLM GPU guidance describes CUDA compatibility library path setup:
https://docs.vllm.ai/en/stable/deployment/docker/

Next evidence needed: the original inner server log if accessible, or a
diagnostic platform execution that surfaces it and host environment. Neither
switching to eager nor outputting zero for all rows repairs a backend that
failed to start. Default zero remains a per-row output recovery mechanism.
No new GPU claims, F1 result or definitive environment cause is reported.

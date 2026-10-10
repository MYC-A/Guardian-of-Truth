# Actual platform environment result — 2026-10-11

Job `lm-mpi-job-39884287-97de-46dc-835a-32e7d2200bbc`, node bmsrv-343.sr006,
ran the fixed diagnostic between 22:04:12–22:04:27 UTC on October10
(01:04:12–01:04:27 Moscow on October11). The intentional exit2 after
DIAGNOSTIC_COMPLETE is expected; this was not an inference/quality run.
No input/gold was read and no prediction was produced.

## Confirmed in this job

| Layer | Actual evidence |
|---|---|
| Child supervisor | Host Python lacks both pidfd bindings. waitid/WNOWAIT fallback ran all five children; each returned0, no cleanup error. |
| Driver libraries | libcuda.so.1 and libnvidia-ml.so.1 both DLOPEN_OK in host Python. |
| GPU | NVIDIA A100-SXM4-80GB, one CUDA device, SM80. nvidia-smi shows81920MiB total/81153MiB free, driver595.71.05. |
| Torch | 2.10.0+cu128, compiled CUDA12.8, available=true; tiny16x16 FP16 matmul completed and synchronized. |
| vLLM host | 0.19.1 imported and selected NvmlCudaPlatform. This does not test engine initialization or weight loading. |
| Model config host | Transformers4.57.1 rejects AutoConfig.for_model(qwen3_5). vLLM registry does contain Qwen3_5ForConditionalGeneration. Registry membership is not complete loading support. |
| Visibility variables | CUDA_VISIBLE_DEVICES is **unset**, not an empty string. NVIDIA_VISIBLE_DEVICES=void coexists with usable GPU here; it must not be interpreted as proof of GPU absence. |

No nvcc/ptxas was found on host PATH; this alone does not demonstrate that an
executed vLLM kernel needs either. No MoE/LoRA kernel was exercised.
The previous pidfd failure was a defect of our tiny diagnostic on host Conda;
it was not the original bundled vLLM startup failure.

## Actual competition ZIP checked independently

`A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip` is still
36,576,333,116 bytes. Reading its contents confirms:

- model config: model_type=qwen3_5, Qwen3_5ForConditionalGeneration;
- bundled Transformers metadata: **5.8.0**, plus qwen3_5 implementation;
- the launcher uses bundled Python and its own loader paths;
- the launcher removes LD_LIBRARY_PATH; the adapter also removes it before
  launching the child;
- no libcuda/libnvidia-ml driver library is bundled.

Host library paths include /usr/local/nvidia/lib and /usr/local/nvidia/lib64.
The bundle does not explicitly forward these host paths. This is a concrete
portability risk, but the host probe does not establish their necessity inside
the private loader: default paths or ldconfig may still resolve the driver.
Do not assign this as the original cause without bundled server evidence.

The original failure remains **unknown below VLLM_START_FAILED**. The original
bundled parent passed its pidfd guard and started a child, which then exited.
Neither the host pidfd issue nor the host Transformers issue explains that
child exit by itself. No failure of model accuracy/B2 has been observed.

## Next action

Keep the verified bundled Transformers/model and B2 decisions, output recovery0,
graphs16 and concurrency unchanged. Package the already-tested startup stderr
reporting (7b20a500) so a real model-start attempt exposes returncode and the
inner traceback. That code is still **not included** in the old full ZIP.
Another host-only diagnostic is not needed: this one answered its questions.

Do not switch wholesale to host Python, upgrade vLLM, disable FlashInfer or
force eager on the basis of this log. If the bundled traceback shows driver
visibility failure, add an explicit host-driver bridge without mixing all
host libraries. If it shows JIT/cache/toolchain failure, fix that specific
executed kernel path. A startup failure cannot be repaired by default0 for all
rows: that recovery belongs to per-row failed replies after inference starts.

Packaging needs care: A: currently has17,307,000,832 free bytes, less than a
second full36.58GB candidate ZIP. Preserve the model, runtime export and Q8
backup. Do not silently delete them to create a diagnostic rebuild.

Independent startup reviewer read the actual log and ZIP and agreed with these
boundaries. Raw v2 log is stored losslessly in diagnostic/platform-probe-v2.log.gz;
its uncompressed SHA is recorded in diagnostic/platform-probe-v2-result.json.

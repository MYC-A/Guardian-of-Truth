# Startup probe v3 (dummy weights) — 2026-10-11

Goal: find why the bundled vLLM child exited (`VLLM_START_FAILED`) without
uploading 29 GB of weights again. Diagnostic only, exit code 2, no input reads,
no predictions. Never submit for scoring.

## What the archive contains
- `runtime/` copied byte-for-byte from the competition ZIP (modes and symlinks kept);
- `model/<REVISION>/` metadata only (config, tokenizer, templates); weight files and
  anything >64 MB are skipped;
- `scripts/predict.py` = `submission/platform_startup_probe.py` (+ helper module).

## What it runs (total budget 1500 s, each server ≤420 s)
1. Host facts: `ldconfig -p` driver entries, `/etc/ld.so.conf*`, `/dev/shm` and `/tmp`
   free space, rlimits, `run_python.sh` text, bundled libcuda presence.
2. Host Python checks with and without `LD_LIBRARY_PATH`: dlopen libcuda/nvml,
   torch matmul, Triton `libcuda_dirs()` and a tiny Triton kernel, vLLM platform.
3. `bundled_exact`: the same checks, then the adapter's exact vLLM command through
   `runtime/python/run_python.sh` with the failed archive's environment
   (LD_LIBRARY_PATH/PYTHONPATH/PYTHONHOME/LD_PRELOAD removed, same caches),
   plus `--load-format dummy`. Waits for `/health`, sends one tiny completion,
   prints return code and the server log tail / first traceback.
4. `bundled_host_compiler` (only if 3 did not serve): same runtime, run_python.sh copy with CC/CXX=/usr/bin/gcc,g++ and host PATH first (v3 run showed bundled gcc.real needs GLIBC_2.36/2.38 on a host <2.36). Replaces the former driver-bridge arm.
5. `host_vllm`: platform Python + vLLM 0.19.1, environment unchanged, dummy weights.

Reading: 3 fails and 4 serves → driver visibility is the cause and the bridge is
the fix. 3 and 4 fail with the same traceback → cause is elsewhere (log shows it).
5 serves → the platform-vLLM path is viable for the real archive.
Limitation: dummy weights skip safetensors reading; everything after (FP8/Marlin
repack, profiling, CUDA graphs, KV cache, sampling) is the real code path.

## Build
```
python scripts/build_platform_startup_probe.py \
  --source-zip A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip \
  --output A:/Guardian-submissions/guardian-startup-probe-v3.zip
```
(or `--source-root <unpacked stage dir>`). Expected size ≈ runtime size (~5.5 GB).
Tests: `tests/test_platform_startup_probe.py`.

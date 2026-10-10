# Compact private-runtime probe — 2026-10-11

Upload **`A:/Guardian-submissions/guardian-bundled-loader-probe-20261011.zip`**
as a separate diagnostic run and share its platform log.
Size **139,532,001 bytes (139.53MB)**, SHA256:
`8a2633f121245c7790d2315b02edd1987795457f7d72d0b8df79465eb9d82ebf`.
It intentionally exits2 without predictions. Never submit it for scoring.
No input/gold is read, no model weights are included or downloaded.

## Why this is different from the previous probe

The previous probe proved host Conda Torch/CUDA/vLLM works on A10080GB,
but our original submission uses a different private Python/ELF loader.
This archive carries the exact runtime/python, runtime/lib and
runtime/toolchain files from the verified server export, plus licenses.
The original launcher is byte-identical to the large submission:
`b81b98943e0327a5b3db82fa78d508d482928adb5e34c55c3648ad62508bd90a`.
The full source runtime ZIP has SHA256
`bd8fae06c167df4b166e708cccc76022e013755efb741409e533c4b3db1f5e2f`.

All wheels and model weights are omitted. The source .pth safely handles the
missing vendor directory; the private Python, glibc loader, libc/libffi/etc
are retained. This is a targeted test of a specific portability boundary,
**not a test of the entire original runtime**.

## Two arms, same read-only CUDA driver code

1. **original_bundled_loader:** unmodified run_python.sh, original private
   library paths. The child prints a startup marker, Python details, CUDA/NVML
   library visibility and loaded native-library paths from /proc/self/maps.
   It calls cuInit and reads device count/name/capability/total memory through
   the CUDA driver API. No model, GPU tensor or kernel computation is run.
2. **driver_path_contrast:** one separate copy of that launcher adds only
   existing host directories containing libcuda.so.1/libnvidia-ml.so.1 after
   the private library paths. It runs the same code. All HPCX paths are not
   blindly inherited. This is diagnostic-only, not a contest runtime change.

The previously verified host supervisor captures/redacts bounded child logs,
uses private process groups, and limits each child to30 seconds. On a platform
without pidfd it retains the leader with waitid/WNOWAIT until group cleanup.
Observe returned statuses; returncode0 alone is not driver success because
the diagnostic code also prints caught driver errors.

## How to interpret

- Original fails, contrast passes: evidence of a driver-path issue in this
  compact composition. Check loaded paths; full vLLM still needs confirmation.
- Both pass: private loader/basic driver initialization works on this worker.
  Next isolate vendor Torch/vLLM/native dependencies or JIT using a larger
  **runtime-only** probe. The complete local runtime ZIP is5.7GB, still no
  30.9GB weights. Do not repeat a36GB upload just to observe imports.
- Both fail: use the precise stderr/driver status/Python-start marker before
  selecting a fix. Do not infer GPU absence from NVIDIA_VISIBLE_DEVICES=void.

Random/dummy weights, if later used to exercise initialization, must be labelled
as such; they cannot verify checkpoint loading, B2 quality or real FP8 inference.
Source-specific results require the actual weights only after this boundary
is understood. Existing successful server inference remains a separate phase.

## Validation and publication

130 tests passed,4 Linux-only tests skipped on Windows. Tests cover retained
original bytes/modes, single-line contrast, source SHA enforcement, omission of
weights/wheels, no input reads/predictions, both arms and custom-wrapper supervision.
The actual archive builder verified every included original member against the
runtime manifest, then every final member SHA/CRC. All4350 entries verified.
Actual source runtime SHA verified before build. No new live GPU test yet.

The large contest ZIP/Q8 backup/downloaded model/runtime are unchanged.
The139MB probe is local; it is not committed as a Git blob. Builder, source,
tests and verification receipt are published in the diagnostic research branch.

Rebuild command (fresh output path; existing artifacts are never overwritten):

```powershell
python scripts/build_bundled_loader_probe.py `
  --runtime A:/Guardian-submissions/vllm-fp8-build-20261010/server-runtime/guardian-vllm-runtime.zip `
  --output A:/Guardian-submissions/<NEW_PROBE_NAME>.zip
```

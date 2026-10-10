# Platform diagnostic follow-up — 2026-10-11

Use **`A:/Guardian-submissions/guardian-platform-env-probe-fixed-20261011.zip`**
for one separate diagnostic run. Size **6989 bytes**, SHA256:
`bdfedc6f55f2ee29d660dbbbfcffcdcf9fb76cbf880d33aa2d9ca4c2d9044ca3`.
Do not use the old probe or the intermediate `probe-v2` artifact.
After uploading, run it and share the common platform log. It intentionally
exits2 without predictions; Failed after the final diagnostic line is expected.
Never submit this archive for competition scoring. It may consume a run attempt.

## What the first platform run establishes

Job `lm-mpi-job-d349d476-a125-4764-9144-9c9292f5d993` reached the probe,
and stdout is captured. Host Python is Conda3.12.12, vLLM0.19.1,
Torch2.10.0, Transformers4.57.1, FlashInfer0.6.6. No nvcc/ptxas
was found on PATH. The host environment exposes custom NVIDIA library paths.

All three import/driver children stopped **before launch** at our optional
Linux pidfd requirement. This is a diagnostic compatibility defect, not proof
of GPU absence or an explanation of the original model-server crash.
The original large submission reached `VLLM_START_FAILED` after its bundled
parent Python passed that guard. These are different runtimes.

The v1 probe maps both unset and empty environment variables to `""`.
It therefore cannot tell whether CUDA_VISIBLE_DEVICES explicitly hides devices.
NVIDIA_VISIBLE_DEVICES=void alone is also inconclusive: NVIDIA describes its
use after CDI has already injected devices in
<https://github.com/NVIDIA/nvidia-container-toolkit/issues/1429>.
Keep absence of visible devices, missing driver libraries, host config support,
and the original hidden vLLM traceback as separate hypotheses.

## Changes limited to the tiny diagnostic

- Probe pidfd open **and** signal0. If unavailable/blocked, use waitid/WNOWAIT
  to retain our unreaped private-session leader until killpg TERM/KILL completes.
  Ownership failure stops signalling. Restore SIGCHLD after reaping; defer
  parent termination through launch/cleanup. Only the probe's group is signalled.
- Print supervisor capabilities and bounded NVIDIA device inventory before
  any child. Unset selected environment variables are null; explicit empty
  values remain empty strings. No visibility variable is overridden.
- Execute bounded nvidia-smi; retain driver-library, Torch availability/memory/
  tiny CUDA matmul, and vLLM-import probes with bounded/redacted log output.
- Test host AutoConfig support for the actual packed model_type qwen3_5 /
  qwen3_5_text, and vLLM registry membership for
  Qwen3_5ForConditionalGeneration. This is config/registry inspection,
  not weight loading or full model execution; no model is downloaded.

Fallback assumes this standalone supervisor is the sole reaper and descendants
remain in its private group. SIGKILL of the supervisor, escaped sessions and
uninterruptible kernel sleep are outside the guarantee. If neither pidfd nor
waitid/WNOWAIT is provided by Python, a child phase reports unavailable rather
than signalling an unowned process.

## Validation and unchanged scope

125 tests passed,4 Linux-only integration tests skipped on Windows. Tests cover
missing/blocked pidfd, no premature reap, refusal to signal a foreign PID,
termination during spawn/cleanup, timeout, bounded redacted output and
unset-versus-empty variables. No live Linux/GPU validation of this revision.
ZIP CRC, all payload hashes and exact contents verified by the builder.
Independent reviewer identified supervisor races; fixes and regression tests
address them. The real fallback integration remains unmeasured.

No contest ZIP, B2 prompts/decisions, inference settings, API retry or default0
policy changed. Commit7b20a500 added startup-log reporting and host metadata;
it did **not** disable FlashInfer or add a killpg fallback to the main adapter.
The main adapter still requires pidfd. Do not switch it to host Python blindly:
host Transformers compatibility is unverified and differs from the bundle.
Do not disable FlashInfer merely because nvcc is absent on host PATH.

The next decision follows the returned evidence. If GPU/driver support fails,
resolve platform exposure/driver visibility. If config support fails, retain
the verified bundled Transformers rather than use host runtime unchanged.
If host probes pass, obtain the main server stderr through the prepared
startup diagnostics before asserting a specific model/kernel fix.

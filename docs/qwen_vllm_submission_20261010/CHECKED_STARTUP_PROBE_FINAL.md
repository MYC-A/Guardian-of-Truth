# Checked startup diagnostic — final artifact, 2026-10-11

Upload **guardian-startup-probe-v3-fixed-20261011.zip** as the next diagnostic run.

Local path: `A:/Guardian-submissions/guardian-startup-probe-v3-fixed-20261011.zip`.

- Size: **5,707,640,927 bytes (5.708 GB)**.
- SHA256: `45eecf8a2caa2381fbb86d611767d6a2bbaca82105183dda35f246256469726c`.
- Frozen code: `96db8c8b4f3431cd336edf9f95057ea9ef72cd17`.
- Branch: `fix/qwen-startup-probe-v3-checked-20261011`.
- Inventory: 52,257 unique ZIP entries; runtime, licenses and model metadata;
  no model weights. All copied members passed decompressed CRC/SHA256 and
  Unix-mode verification against the source manifest. Final archive SHA computed.
- Embedded diagnostic code matches the frozen source files.
- Windows: **156 passed, 10 skipped**. Linux: **81 passed**.
- Linux CI: https://github.com/MYC-A/Guardian-of-Truth/actions/runs/38092325305

The earlier `guardian-startup-probe-v3-checked-20261011.zip` is superseded: it
predates the cleanup race correction. Upload only the **v3-fixed** filename above.
The original competition ZIP, real model weights and Q8 backup were preserved.

## Run and send back

1. Upload this diagnostic ZIP through the same platform pipeline and start it.
2. Download the common platform log after it finishes. Expected final code is 2
   and the platform will display Failed: no predictions file is produced.
3. Send that log. Relevant entries start with `GUARDIAN_ENV_PROBE`; they include
   bundled-library checks, engine status and bounded engine log head/tail.

The first engine uses the bundled runtime and original graphs16 FP8 settings
with `--load-format dummy`. The second tests host vLLM, if cleanup and remaining
time allow it. Overall diagnostic budget: 1500 seconds with bounded phases and
teardown. Actual platform duration is not yet measured.

The compact previous probe proved driver initialization, not vendor-kernel or
engine startup. This diagnostic has **not yet run on the target GPU**. Dummy
weights differ from real checkpoint loading; success is not B2 quality/timing
validation. The original startup cause remains unknown until its trace is
obtained. This archive changes no B2 decisions and reads no task inputs.

## Evidence

- `diagnostic/checked-v3-final-build.json`: compact build and test receipt.
- Local full inventory: `A:/Guardian-submissions/guardian-startup-probe-v3-fixed-20261011.verification.json`.
- Local checksum: `A:/Guardian-submissions/guardian-startup-probe-v3-fixed-20261011.zip.sha256`.
- `CHECKED_STARTUP_PROBE_GUIDE.md`: protocol and limitations.
- `CHECKED_STARTUP_PROBE_REVIEW.md`: independent reviews and reproduced defects.
- `diagnostic/linux-ci-96db8c8b.log`: Linux test log.

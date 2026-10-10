# Submission preparation status — 2026-10-10

Branch: `build/qwen-vllm-fp8-submission-20261010`.

## Verified

Server export at `/workspace/guardian/vllm_submission_build_20261010_v4`
completed from source `65bf34384929a6001132d8dd6e6a8be51298d990`.
Prepare, CPU imports/child Python, native tools, empty-input and public empty
Parquet entrypoint checks all returned 0. Runtime export returned 0 after
253.65 seconds. Files: `guardian-vllm-runtime.zip`, `runtime-export.json`,
`DONE.json`. This phase did not execute GPU validation.

Local packaging regression checks: 92 passed, covering builder, assembler
and public entrypoint. Local invocation requires `PYTHONPATH=src`.

## CI repair

Run 38054250819 failed because Linux protected-hardlink restrictions prevented
linking root-owned `/usr/bin/python3.12` into the stage. The builder now copies
on EPERM/EACCES, without modifying the source. Other link errors still fail.
New contrast checks exercise permission fallback and disk-full propagation.
CI native dependencies include OpenMPI, PMIx and TBB to match the successful
server environment. These changes affect packaging only, not B2 decisions.

## Weights and remaining work

21 of 78 pinned assets were SHA256 verified locally; 57 remain missing.
The native curl attempt failed without successful chunks. Manual download
was selected by the user. Links and destination instructions are in
`A:/Guardian-submissions/vllm-fp8-build-20261010/DOWNLOAD_MISSING_FILES.html`.
Do not treat `.partial` or `.crdownload` as complete model files.

The previous CI artifact fetcher recorded FAILED because its CI failed.
Runtime transfer to the local PC is not yet verified. A new successful CI
must yield a separately checked runtime transport; the server export remains
available independently. Neither export is the final competition ZIP.

After all assets arrive: verify hashes, assemble runtime and model with
`scripts/assemble_vllm_submission.py`, verify the final ZIP and size cap,
then execute a GPU public-entrypoint run. Historical inference results do
not substitute for testing this assembled archive. Preserve the old ZIP.

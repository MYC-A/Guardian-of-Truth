# Full submission toolchain repair, 2026-10-11

Source ZIP: `guardian-qwen-vllm-fp8-graphs16.zip`, SHA256
`ce6fc68434d81375ec81f33139c70f5e14954e880fc8ba32bd22421b4876e336`.

Platform diagnostic job `lm-mpi-job-90ee5438-de71-4834-8594-324a508a1b95`
confirmed bundled Python/Triton/vLLM startup with repaired private library
paths: ready in 352.9 seconds, HTTP 200, eight generated tokens. Its dummy
weights produced newline content. This is runtime evidence, not model quality
or a real-checkpoint load. Platform log SHA256:
`f7d44d143d47e571974713e2da27beac3930e19bd06d0909e646bd04e0b06431`.

The remaining LTO issue was a direct re-exec of `g++.real` via `COLLECT_GCC`.
The `lto-wrapper` shell boundary now maps the two bundled native compiler paths
back to their loader wrappers. Other paths are untouched. GNU GCC 13 reads
this variable to select its LTO driver:
https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-13/gcc/lto-wrapper.cc

Development Linux verification (glibc 2.39): gcc and g++, each with no LTO,
`-flto`, and `-flto=2`, compiled two translation units into shared libraries;
all six libraries loaded and returned 42. Instrumentation in temporary test
copies observed three compiler-wrapper entries per LTO link, including the
LTO response-file arguments. This validates the reentry mechanism, while the
exact platform glibc was not reproduced. Local checks: 253 passed, 10 skipped
because they require a POSIX environment.

The full repair operator preserves all frozen entries except ten toolchain
wrappers and the adapter's startup diagnostics; it adds one native mapper
copy and rebuilds the manifest inventory. The original build source identity
is preserved and the repair is recorded separately. Model assets, B2 code,
public entrypoint, Python launcher, runtime versions and inference settings
are retained. No system-compiler fallback or compilation cache is introduced.
Startup failure diagnostics print a bounded redacted log tail and retain the
original exception without retries. Existing startup timeout: 600 seconds.

Build command from the checked checkout:

```powershell
python scripts/repair_full_vllm_submission.py --source-zip A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip --output A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16-toolchain-fixed-20261011.zip
```

The operator hashes the whole source ZIP, copies compressed records without
extracting weights, verifies every final member's SHA256/CRC/permissions,
checks the 40 GB cap, hashes the output and publishes it exclusively. Adjacent
`.verification.json` and `.zip.sha256` receipts identify the final artifact.

Upload the repaired full ZIP for a real submission. The next platform run
must establish real checkpoint loading, predictions/Parquet output and whole
script time on the actual cohort. Do not infer that the full/private run fits
30 minutes from the dummy startup or historical development inference time.

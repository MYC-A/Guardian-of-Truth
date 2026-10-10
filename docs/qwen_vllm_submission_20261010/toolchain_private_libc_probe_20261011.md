# Toolchain libc diagnostic

The supplied Cloud.ru log confirms that gcc.real fails while compiling Triton's
cuda_utils.c. Existing compiler wrappers already invoke the private ELF loader,
but only search runtime/lib. The bundled libc is in the compiler sysroot instead.
The wrapper repair adds the sysroot library directories for every compiler child,
including gcc, g++, as, ld, cc1, cc1plus, collect2, lto1, lto-wrapper and mapper.
Native compiler binaries remain byte-identical; the mapper receives a wrapper.

The diagnostic runs two cold-server arms with separate caches:

1. Bundled Python, packages and repaired bundled compiler.
2. The same bundled Python/packages with /usr/bin/gcc and /usr/bin/g++.

Each arm compiles and loads C, C++, and C++ LTO shared libraries (expected value
42), runs a Triton kernel, then starts the graphs16 vLLM profile with dummy weights
and makes one chat request. The system-compiler selector survives Python child
restarts. It is opt-in; the default remains bundled compilation.

Build on Windows without extracting the large source archive:

```powershell
python scripts/build_platform_startup_probe.py --repair-toolchain --source-zip A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip --output A:/Guardian-submissions/guardian-startup-probe-toolchain-fix-20261011.zip
```

The builder checks the old wrapper hashes against the source manifest, preserves
compressed records for unchanged members, then reads every output member and
verifies SHA256, CRC and permissions before publishing. The output manifest records
the original and repaired wrapper hashes. repair_vllm_toolchain.archive_patches is
also the patch source for the eventual full submission, after the GPU test result.

Read GUARDIAN_STARTUP_PROBE validation: bundled_compiler_passed and
system_compiler_passed require successful dependency checks, completion or an
empty dummy completion with positive generated-token count and finish reason,
and confirmed GPU release. Raw bounded, redacted API responses remain in the log
even on parsing failure. A 200 response alone does not pass validation.

Expected platform status is Failed/exit 2: this diagnostic intentionally produces
no predictions. Return the full platform log. Local Windows tests cannot execute
the Linux compiler or GPU runtime; those remain the purpose of this upload.

Dummy weights do not establish real checkpoint loading, quality, full-set runtime
or submission success. Build the full submission only after reviewing this run.
